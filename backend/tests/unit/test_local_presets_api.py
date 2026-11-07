import pytest


@pytest.mark.asyncio
async def test_get_local_preset_templates(async_client):
    res = await async_client.get("/api/v1/local-presets/templates")
    assert res.status_code == 200
    data = res.json()
    assert "filament" in data
    assert "process" in data
    assert len(data["filament"]) >= 4
    assert len(data["process"]) >= 4

    # Verify PLA template
    pla = next(p for p in data["filament"] if p["id"] == "tpl_pla")
    assert pla["filament_type"] == "PLA"
    assert "nozzle_temperature" in pla["setting"]

    # Verify Standard Process template
    std = next(p for p in data["process"] if p["id"] == "tpl_proc_standard")
    assert std["setting"]["tree_support_wall_count"] == "0"


@pytest.mark.asyncio
async def test_create_and_clone_local_preset(async_client):
    # 1. Create a process preset with a negative sentinel to test sanitization
    create_payload = {
        "name": "Mein Test Profil",
        "preset_type": "process",
        "setting": {
            "type": "process",
            "layer_height": "0.2",
            "wall_loops": "3",
            "tree_support_wall_count": "-1",  # Sentinel that OrcaSlicer CLI would reject
        },
    }
    res = await async_client.post("/api/v1/local-presets/", json=create_payload)
    assert res.status_code == 200, res.text
    created = res.json()
    preset_id = created["id"]
    assert created["name"] == "Mein Test Profil"

    # Check detail endpoint and verify sanitization
    res_detail = await async_client.get(f"/api/v1/local-presets/{preset_id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["setting"]["tree_support_wall_count"] == "0"

    # 2. Clone the preset
    res_clone = await async_client.post(f"/api/v1/local-presets/{preset_id}/clone")
    assert res_clone.status_code == 200
    cloned = res_clone.json()
    assert cloned["id"] != preset_id
    assert cloned["name"] == "Mein Test Profil (Kopie)"
    assert cloned["source"] == "clone"

    # 3. Clone again to test incremental name
    res_clone2 = await async_client.post(f"/api/v1/local-presets/{preset_id}/clone")
    assert res_clone2.status_code == 200
    cloned2 = res_clone2.json()
    assert cloned2["name"] == "Mein Test Profil (Kopie 2)"

    # 4. Update the cloned preset
    update_payload = {
        "name": "Mein Aktualisiertes Profil",
        "setting": {
            "layer_height": "0.16",
            "tree_support_wall_count": "-1",
        },
    }
    res_up = await async_client.put(f"/api/v1/local-presets/{cloned['id']}", json=update_payload)
    assert res_up.status_code == 200
    assert res_up.json()["name"] == "Mein Aktualisiertes Profil"

    # 5. Delete presets
    del1 = await async_client.delete(f"/api/v1/local-presets/{preset_id}")
    assert del1.status_code == 200
    del2 = await async_client.delete(f"/api/v1/local-presets/{cloned['id']}")
    assert del2.status_code == 200
    del3 = await async_client.delete(f"/api/v1/local-presets/{cloned2['id']}")
    assert del3.status_code == 200
