"""Exercise the real coordinator with in-memory HA services; never play audio."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import load_module

ROOT = Path(__file__).parents[1] / "custom_components" / "kslive"


@pytest.fixture
def runtime(monkeypatch):
    """Stub only HA boundaries so the real lifecycle implementation is tested."""
    def module(name, **attributes):
        value = types.ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    class Coordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, hass, **_kwargs):
            self.hass = hass
            self.data = None
            self.updates = 0

        def async_set_updated_data(self, data):
            self.data = data
            self.updates += 1

        def async_update_listeners(self):
            self.updates += 1

    class Store:
        saved = {}

        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.saved.get(self.key)

        async def async_save(self, value):
            self.saved[self.key] = dict(value)

    class HAError(Exception):
        pass

    module("homeassistant")
    module("homeassistant.components")
    module(
        "homeassistant.components.media_player",
        DOMAIN="media_player",
        async_process_play_media_url=lambda _hass, path: f"http://ha.test:8123{path}",
    )
    module("homeassistant.components.media_player.const", SERVICE_PLAY_MEDIA="play_media")
    module("homeassistant.config_entries", ConfigEntry=object)
    module("homeassistant.const", ATTR_ENTITY_ID="entity_id", EVENT_STATE_CHANGED="state_changed")
    module("homeassistant.core", Event=object, HomeAssistant=object, callback=lambda func: func)
    module("homeassistant.exceptions", ConfigEntryAuthFailed=HAError, HomeAssistantError=HAError)
    module("homeassistant.helpers")
    module("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.registry)
    module("homeassistant.helpers.device_registry", async_get=lambda hass: hass.devices)
    module("homeassistant.helpers.storage", Store=Store)
    module(
        "homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator,
        UpdateFailed=HAError,
    )
    module("kslive_runtime", __path__=[str(ROOT)])
    for name in ("api", "const", "models", "output_names", "playback_state", "streaming"):
        monkeypatch.setitem(sys.modules, f"kslive_runtime.{name}", load_module(name))
    module("kslive_runtime.audio_proxy", KSLiveAudioProxy=object)
    module("kslive_runtime.equalizer", KSLiveEqualizer=object)

    def load(name):
        spec = importlib.util.spec_from_file_location(f"kslive_runtime.{name}", ROOT / f"{name}.py")
        implementation = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, implementation)
        spec.loader.exec_module(implementation)
        return implementation

    implementation = load("coordinator")

    class Registry(dict):
        def async_get(self, key):
            return self.get(key)

    class Bus:
        def __init__(self):
            self.listener = None

        def async_listen(self, _event, listener):
            self.listener = listener
            return lambda: setattr(self, "listener", None)

    class Services:
        def __init__(self):
            self.calls = []
            self.on_play = None
            self.fail = False

        async def async_call(self, domain, service, data, **_kwargs):
            self.calls.append((domain, service, data))
            if service == "play_media":
                if self.fail:
                    raise HAError("Mock output unavailable")
                if self.on_play:
                    self.on_play(data)

    class Client:
        def __init__(self):
            self.calls = []
            self.started = asyncio.Event()
            self.gate = asyncio.Event()
            self.gate.set()
            self.fail = False

        async def async_playback_url(self, content_id):
            self.calls.append(content_id)
            self.started.set()
            await self.gate.wait()
            if self.fail:
                raise load_module("api").KSLiveApiError("Mock API unavailable")
            return f"https://media.test/{content_id}.m3u8"

    class Proxy:
        def __init__(self):
            self.created = []
            self.stopped = []
            self.active = set()

        async def async_create_path(self, target, _url):
            self.created.append(target)
            self.active.add(target)
            return f"/api/kslive/audio/{len(self.created)}.mp3"

        async def async_stop_target(self, target):
            self.stopped.append(target)
            self.active.discard(target)

    class Equalizer:
        def __init__(self):
            self.settings = SimpleNamespace(enabled=True)
            self.snapshots = set()
            self.applied = []
            self.restored = []
            self.on_apply = None

        async def async_apply(self, targets):
            self.applied.extend(targets)
            self.snapshots.update(targets)
            if self.on_apply:
                self.on_apply()

        async def async_restore(self, targets):
            self.restored.extend(targets)
            self.snapshots.difference_update(targets)

        async def async_restore_all(self):
            await self.async_restore(tuple(self.snapshots))

        async def async_set(self, key, value):
            setattr(self.settings, key, value)

    def make(players=("media_player.lounge", "media_player.garage")):
        hass = SimpleNamespace(
            states=Registry(), registry=Registry(), devices=Registry(),
            bus=Bus(), services=Services(),
            async_create_task=lambda coro, name: asyncio.create_task(coro, name=name),
        )
        for target in (*players, "media_player.override"):
            hass.registry[target] = SimpleNamespace(
                platform="sonos", name=None, original_name="Speaker", device_id=target,
            )
            hass.devices[target] = SimpleNamespace(name_by_user=None, name=target.split(".")[1])
        entry = SimpleNamespace(entry_id="test", options={"media_players": list(players)})
        coordinator = implementation.KSLiveCoordinator(hass, entry, Client(), Proxy(), Equalizer())
        content = SimpleNamespace(content_id=42)
        coordinator.data = SimpleNamespace(playable=content, playable_items=(content,))
        coordinator.start_tracking()
        return coordinator

    def state(coordinator, target, value, media_id=None):
        coordinator.hass.states[target] = SimpleNamespace(
            state=value, attributes={"media_content_id": media_id, "friendly_name": "Live name"},
        )
        if coordinator.hass.bus.listener:
            coordinator.hass.bus.listener(SimpleNamespace(data={"entity_id": target}))

    return SimpleNamespace(
        make=make, state=state, implementation=implementation, error=HAError,
        module=module, load=load,
    )


def test_play_joins_pending_api_request_and_buffering_requests(runtime):
    async def run():
        coordinator = runtime.make()
        coordinator.client.gate.clear()
        first = asyncio.create_task(coordinator.async_play())
        await coordinator.client.started.wait()
        second = asyncio.create_task(coordinator.async_play(media_players=["media_player.lounge"]))
        await asyncio.sleep(0)
        assert coordinator.playback_starting
        assert coordinator.client.calls == [42]
        coordinator.client.gate.set()
        await asyncio.gather(first, second)
        await coordinator.async_play()
        assert coordinator.client.calls == [42]
        assert coordinator.audio_proxy.created == ["media_player.lounge"]
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_selected_output_is_saved_before_return_and_used_by_default(runtime):
    async def run():
        coordinator = runtime.make()
        await coordinator.async_select_source("garage")
        restored = runtime.make()
        await restored.async_load_output()
        assert restored.selected_targets == ("media_player.garage",)
        await coordinator.async_play()
        assert coordinator.audio_proxy.created == ["media_player.garage"]
        await coordinator.async_play(media_players=["media_player.override"])
        assert coordinator.active_targets == ("media_player.override",)
        await coordinator.async_shutdown()
        assert not coordinator.audio_proxy.active
        assert not coordinator.equalizer.snapshots
        assert coordinator.hass.bus.listener is None
        await restored.async_shutdown()
    asyncio.run(run())


def test_old_sonos_source_during_eq_does_not_clear_startup_grace(runtime):
    async def run():
        coordinator = runtime.make()
        target = "media_player.lounge"
        coordinator.equalizer.on_apply = lambda: runtime.state(
            coordinator, target, "playing", "spotify:old-track"
        )
        await coordinator.async_play()
        session = coordinator._sessions[target]
        assert not session.established
        assert coordinator.playback_starting
        runtime.state(coordinator, target, "buffering", session.media_url)
        await coordinator.async_play()
        assert len(coordinator.audio_proxy.created) == 1
        assert session.deadline > runtime.implementation.time.monotonic() + 20
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_external_takeover_releases_only_affected_speaker_and_excludes_eq(runtime):
    async def run():
        coordinator = runtime.make()
        targets = coordinator.configured_players
        await coordinator.async_play(media_players=list(targets))
        for target in targets:
            runtime.state(coordinator, target, "playing", coordinator._sessions[target].media_url)
        runtime.state(coordinator, targets[0], "playing", "spotify:new-track")
        await coordinator.async_set_equalizer("bass", 3)
        assert coordinator.equalizer.applied[-1] == targets[1]
        cleanup = coordinator._cleanup_tasks.get(targets[0])
        if cleanup:
            await cleanup
        assert coordinator.active_targets == (targets[1],)
        assert coordinator.equalizer.snapshots == {targets[1]}
        assert coordinator.audio_proxy.active == {targets[1]}
        assert not any(call[1] == "media_stop" for call in coordinator.hass.services.calls)
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_stop_cancels_pending_start_without_dispatching_audio(runtime):
    async def run():
        coordinator = runtime.make()
        coordinator.client.gate.clear()
        pending = asyncio.create_task(coordinator.async_play())
        await coordinator.client.started.wait()
        await coordinator.async_stop()
        with pytest.raises(asyncio.CancelledError):
            await pending
        coordinator.client.gate.set()
        assert not coordinator.playback_active
        assert coordinator.hass.services.calls == []
        assert coordinator.audio_proxy.created == []
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_api_failure_allows_retry_and_service_failure_restores_effects(runtime):
    async def run():
        coordinator = runtime.make()
        coordinator.client.fail = True
        with pytest.raises(runtime.error):
            await coordinator.async_play()
        assert not coordinator.playback_active
        coordinator.client.fail = False
        coordinator.hass.services.fail = True
        with pytest.raises(runtime.error):
            await coordinator.async_play()
        assert not coordinator.playback_active
        assert not coordinator.audio_proxy.active
        assert not coordinator.equalizer.snapshots
        coordinator.hass.services.fail = False
        await coordinator.async_play()
        assert coordinator.playback_active
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_output_labels_do_not_change_when_sonos_loads_and_collisions_are_unique(runtime):
    async def run():
        coordinator = runtime.make()
        before = coordinator.output_sources
        updates = coordinator.updates
        runtime.state(coordinator, "media_player.lounge", "idle")
        assert coordinator.output_sources == before
        assert coordinator.updates > updates
        assert "media_player.lounge" not in before
        coordinator._output_labels.clear()
        for device in coordinator.hass.devices.values():
            device.name = "All configured speakers"
        sources = coordinator.output_sources
        assert len(sources) == 3
        assert sources["All configured speakers"] == coordinator.configured_players
        assert sources == coordinator.output_sources
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_paused_owned_session_resumes_without_replacing_relay(runtime):
    async def run():
        coordinator = runtime.make()
        await coordinator.async_play()
        target = coordinator.active_targets[0]
        runtime.state(coordinator, target, "paused", coordinator._sessions[target].media_url)
        await coordinator.async_play()
        assert len(coordinator.audio_proxy.created) == 1
        assert coordinator.hass.services.calls[-1][1] == "media_play"
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_real_platform_setup_creates_all_entities_and_play_entry_points_join(runtime):
    async def run():
        coordinator = runtime.make()
        coordinator.hass.data = {"kslive": {"test": coordinator}}

        class Entity:
            def __init__(self, coordinator):
                self.coordinator = coordinator
                self.hass = coordinator.hass

        runtime.module("kslive_runtime.entity", KSLiveEntity=Entity)
        runtime.module(
            "homeassistant.helpers.entity_platform", AddConfigEntryEntitiesCallback=object,
        )
        sys.modules["homeassistant.const"].EntityCategory = SimpleNamespace(CONFIG="config")
        media = sys.modules["homeassistant.components.media_player"]
        media.BrowseMedia = object
        media.MediaClass = SimpleNamespace(MUSIC="music", DIRECTORY="directory")
        media.MediaPlayerDeviceClass = SimpleNamespace(SPEAKER="speaker")
        media.MediaPlayerEnqueue = object
        media.MediaPlayerEntity = type("MediaPlayerEntity", (), {})
        media.MediaPlayerEntityFeature = object
        media.MediaPlayerState = SimpleNamespace(
            IDLE="idle", BUFFERING="buffering", PLAYING="playing", PAUSED="paused", OFF="off",
        )
        media.MediaType = SimpleNamespace(MUSIC="music")
        for name, entity in (
            ("button", "ButtonEntity"), ("sensor", "SensorEntity"),
            ("select", "SelectEntity"), ("number", "NumberEntity"), ("switch", "SwitchEntity"),
        ):
            runtime.module(f"homeassistant.components.{name}", **{entity: type(entity, (), {})})
        sys.modules["homeassistant.components.number"].NumberMode = SimpleNamespace(SLIDER="slider")
        entities = []
        for platform in load_module("const").PLATFORMS:
            component = runtime.load(platform)
            await component.async_setup_entry(coordinator.hass, coordinator.entry, entities.extend)
        assert len(entities) == 9
        assert len({entity._attr_unique_id for entity in entities}) == 9
        output = next(entity for entity in entities if entity._attr_name == "Output")
        await output.async_select_option("garage")
        player = next(entity for entity in entities if entity._attr_name == "Player")
        button = next(entity for entity in entities if entity._attr_name == "Play audio")
        coordinator.client.gate.clear()
        first = asyncio.create_task(button.async_press())
        await coordinator.client.started.wait()
        second = asyncio.create_task(player.async_media_play())
        third = asyncio.create_task(coordinator.async_play())  # kslive.play handler's call
        await asyncio.sleep(0)
        assert player.state == "buffering"
        assert output.current_option == "garage"
        assert player.source_list == output.options
        coordinator.client.gate.set()
        await asyncio.gather(first, second, third)
        assert coordinator.audio_proxy.created == ["media_player.garage"]
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_real_equalizer_restores_original_values_and_skips_unknown_values(runtime):
    async def run():
        coordinator = runtime.make()
        hass = coordinator.hass
        controls = [
            SimpleNamespace(platform="sonos", translation_key=key, entity_id=f"{domain}.{key}")
            for key, domain in (("bass", "number"), ("treble", "number"), ("loudness", "switch"))
        ]
        sys.modules["homeassistant.helpers.entity_registry"].async_entries_for_device = (
            lambda *_args, **_kwargs: controls
        )
        runtime.module(
            "kslive_runtime.equalizer_settings",
            **{
                name: getattr(load_module("equalizer_settings"), name)
                for name in ("EqualizerSettings", "bounded_number", "settings_from_mapping")
            },
        )
        equalizer = runtime.load("equalizer").KSLiveEqualizer(hass, "test")
        hass.states["number.bass"] = SimpleNamespace(state="-3")
        hass.states["number.treble"] = SimpleNamespace(state="unavailable")
        hass.states["switch.loudness"] = SimpleNamespace(state="off")
        await equalizer.async_apply(("media_player.lounge",))
        applied = list(hass.services.calls)
        assert {call[2]["entity_id"] for call in applied} == {"number.bass", "switch.loudness"}
        hass.states["number.bass"].state = "4"
        await equalizer.async_apply(("media_player.lounge",))
        await equalizer.async_restore_all()
        assert hass.services.calls[-2:] == [
            ("number", "set_value", {"entity_id": "number.bass", "value": -3}),
            ("switch", "turn_off", {"entity_id": "switch.loudness"}),
        ]
        assert equalizer._snapshots == {}
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_startup_deadline_releases_a_stalled_relay_without_real_waits(runtime):
    async def run():
        coordinator = runtime.make()
        await coordinator.async_play()
        target = coordinator.active_targets[0]
        session = coordinator._sessions[target]
        runtime.implementation.time = SimpleNamespace(monotonic=lambda: session.deadline + 1)
        await coordinator._async_cleanup_target(target, session, 0)
        assert not coordinator.playback_active
        assert not coordinator.audio_proxy.active
        assert not coordinator.equalizer.snapshots
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_rebuffering_defers_earlier_idle_cleanup_until_its_own_deadline(runtime):
    async def run():
        coordinator = runtime.make()
        await coordinator.async_play()
        target = coordinator.active_targets[0]
        session = coordinator._sessions[target]
        runtime.state(coordinator, target, "playing", session.media_url)
        runtime.state(coordinator, target, "idle", session.media_url)
        original_timer = coordinator._cleanup_tasks[target]
        runtime.state(coordinator, target, "buffering", session.media_url)
        await coordinator._async_cleanup_target(target, session, 0)
        assert coordinator.playback_active
        assert coordinator._cleanup_tasks[target] is not original_timer
        original_timer.cancel()
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_same_speaker_set_in_different_order_does_not_replace_relays(runtime):
    async def run():
        coordinator = runtime.make()
        targets = list(coordinator.configured_players)
        await coordinator.async_play(media_players=targets)
        await coordinator.async_play(media_players=list(reversed(targets)))
        assert coordinator.client.calls == [42]
        assert coordinator.audio_proxy.created == targets
        await coordinator.async_shutdown()
    asyncio.run(run())


def test_takeover_restoration_does_not_wait_for_another_playback_url(runtime):
    async def run():
        coordinator = runtime.make()
        await coordinator.async_play()
        target = coordinator.active_targets[0]
        runtime.state(coordinator, target, "playing", coordinator._sessions[target].media_url)
        coordinator.client.started.clear()
        coordinator.client.gate.clear()
        next_play = asyncio.create_task(coordinator.async_play(content_id=43))
        await coordinator.client.started.wait()
        runtime.state(coordinator, target, "playing", "spotify:new-track")
        await coordinator._cleanup_tasks[target]
        assert coordinator.equalizer.snapshots == set()
        assert coordinator.audio_proxy.active == set()
        coordinator.client.gate.set()
        await next_play
        await coordinator.async_shutdown()
    asyncio.run(run())
