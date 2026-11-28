# Migrating from the "Thermia Heat Pump" integration

This guide is for people who already run [`klejejs/ha-thermia-heat-pump-integration`](https://github.com/klejejs/ha-thermia-heat-pump-integration) (domain `thermia`) with automations, scenes or dashboards built on it, and want to move to Thermia Cloud. The two integrations can run **side by side** (different domains, different entities), so you can migrate in small, reversible steps.

## The one thing to know first: two different "water heaters"

| | Old integration | Thermia Cloud |
|---|---|---|
| `water_heater.<name>` | The **operation mode of the heat pump**: `AUTO`, `OFF`, `HOT_WATER`, `COMPRESSOR`, `AUXILIARY` | The **hot water mode**: `comfort`, `economy`, `away` (plus `off`) |
| Operation mode of the heat pump | the `water_heater` above | `select.<name>_operation_mode`: `auto`, `off`, `hot_water`, `compressor`, `auxiliary` |
| Hot water on/off | `switch.<name>_hot_water` | `switch.<name>_hot_water` (and the `water_heater` turn on/off) |

So `water_heater.set_operation_mode` with `AUTO` / `OFF` / `HOT_WATER` in an old automation **must become** `select.select_option` on the *operation mode* select, not a call on the new `water_heater`. Renaming the entity alone would send `AUTO` to the hot water mode, which does not exist there.

```yaml
# before
- action: water_heater.set_operation_mode
  target: {entity_id: water_heater.my_pump}
  data: {operation_mode: AUTO}
# after
- action: select.select_option
  target: {entity_id: select.my_pump_operation_mode}
  data: {option: auto}
```

## Entity mapping

Entity ids depend on your language and area; look yours up under *Settings → Devices & services → Thermia Cloud*.

| Old | New |
|---|---|
| `sensor.<name>_outdoor_temperature` | Outdoor temperature |
| `sensor.<name>_supply_line_temperature` | Supply temperature |
| `sensor.<name>_desired_supply_line_temperature` | Desired supply temperature |
| `sensor.<name>_hot_water_temperature` | Hot water temperature |
| `sensor.<name>_compressor_operational_time`, `…_heating_…`, `…_hot_water_…` | Operating hours (compressor, heating, hot water, auxiliary heaters) |
| `binary_sensor.<name>_*_operational_status` | Compressor in operation / Heating active / Defrosting / … |
| `switch.<name>_hot_water` | Hot water (switch) |
| `water_heater.<name>` (operation mode) | Operation mode (select) |
| `number.<name>_*heat*curve*` | Heating curve (main circuit / mixing circuit 1) |
| `sensor.<name>_pid` | no equivalent (not a Thermia register any more) |

## Recommended steps

1. **Back up** Home Assistant (*Settings → System → Backups*).
2. **Install Thermia Cloud** next to the old integration and choose *Monitor only (read-only)* in the last step. Compare the values for a few days.
3. **Make `_old` copies** of every automation and scene that uses the old entities and turn the copies off. They are your rollback.
4. **Switch writing on** (*Configure → General → Safety → Read-only mode* off). Test one harmless write first (the hot water mode, then the hot water switch). A heating curve change by 1 °C is the next step; do it right after any script that also writes it has run.
5. **Re-point the originals** to the new entities, one automation at a time, following the table above. Scenes: replace the old operation mode and hot water entries with the select and the new switch. Dashboards: replace the entities and the `water_heater` calls.
6. **Scripts that wrote to the cloud themselves** (for example an AppDaemon app writing the curve registers): never let the old script and the new automation run at the same time. Disable the script first, then enable the automation that sets the new `number` entities.
7. **Watch it for a week.** Then delete the `_old` copies, the old script and, last, remove the old integration (after another backup).

Rollback at any step: turn the new automation off and the `_old` copy on. Removing Thermia Cloud does not touch the old integration.

## Several circuits from one slider

If one `input_number` drives the heating curve of the main circuit and a mixing circuit, a plain automation does it:

```yaml
triggers:
  - trigger: state
    entity_id: input_number.heating_curve
    for: {seconds: 1}
actions:
  - action: number.set_value
    target: {entity_id: number.my_pump_heating_curve_main_circuit}
    data: {value: "{{ states('input_number.heating_curve') | float }}"}
    continue_on_error: true
  - action: number.set_value
    target: {entity_id: number.my_pump_mixing_circuit_1_heating_curve}
    data: {value: "{{ states('input_number.heating_curve') | float }}"}
    continue_on_error: true
```

Writes are validated against the limits the cloud reports, shown immediately as pending and confirmed by a read-back.
