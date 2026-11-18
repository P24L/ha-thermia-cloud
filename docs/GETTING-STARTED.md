# Getting started

A step-by-step guide for people who have never used the integration. It takes about ten minutes.

## What you need

- A Thermia heat pump that is connected to **Thermia Online / MyThermia** (the account you use in the Thermia app).
- Home Assistant **2026.10** or newer. With 2026.11 or newer the built-in **Marketplace** installs the integration; older versions use HACS.

## 1. Install

1. *Settings → Marketplace* → ⋮ (top right) → **Add from link**.
2. Enter `P24L/ha-thermia-cloud` and choose **Download**.
3. The setup dialog opens right away. If Home Assistant asks for a restart, do it and add the integration afterwards under *Settings → Devices & services → Add integration → Thermia Cloud (unofficial)*.

## 2. Set up

1. **Sign in** with the e-mail and password of your Thermia account. They are stored in Home Assistant only, to sign in again when the saved session expires.
2. If the account has several heat pumps you pick which ones to add (you can change this later).
3. **Choose the mode:**
   - *Monitor and control* – you can change settings such as the heating curve, hot water and the operation mode.
   - *Monitor only (read-only)* – the integration can never write anything to your heat pump. A good start if you only want to look first. You can change this at any time under *Configure → General → Safety*.

Home Assistant then creates your heat pump as a **device** (and a second device for each additional heating circuit).

## 3. What you will see

| Where | What |
|---|---|
| **Controls** | Heating curve (main circuit, and circuit 1), hot water on/off, operation mode, hot water mode |
| **Sensors** | Outdoor, supply and hot water temperature, operating hours, compressor / heating / hot water / defrost status |
| **Diagnostic** | Online, last contact with the cloud, alarms, *Refresh names*, *Rediscover registers* |
| **+ disabled entities** | Less common values the heat pump offers. Open the device, choose the link *+ N disabled entities* and enable what you want |

Some entries only exist in a certain state of the heat pump – for example *hot water mode* only while hot water is switched on, or *constant temperature* only while a circuit is in *Constant* mode. They appear by themselves when the pump changes state.

## 4. Changing settings safely

- **Heating curve** – the single most useful setting. It tells the heat pump how warm the water for your radiators should be. Raise it by 1 °C, wait a day, and see whether the house feels better. Small steps are the rule; a heating curve that is too low in winter can leave a house cold.
- **Hot water** – the switch turns it on or off; the *hot water mode* selects comfort, economy or away.
- **Operation mode** – *Off* stops heating as well. Do not leave a house without heating in frost.
- Every change is checked against the limits the cloud reports, shown immediately, and confirmed by reading it back (the entity shows *pending value* until then).
- Want to be sure nothing is ever changed? Turn on **Read-only mode**.

## 5. Useful extras

- **Automation blueprints** – get a notification when the heat pump reports an alarm or goes offline:
  [![Alarm](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FP24L%2Fha-thermia-cloud%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fthermia_cloud%2Falarm_notification.yaml)
  [![Offline](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FP24L%2Fha-thermia-cloud%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fthermia_cloud%2Fconnection_lost.yaml)
- **A first dashboard** – open the device page and use *Add to dashboard* on the *Controls* and *Sensors* cards. Or paste this into a dashboard in YAML mode (replace the entity ids with your own, see *Settings → Entities*):

  ```yaml
  type: entities
  title: Heat pump
  entities:
    - entity: switch.my_heat_pump_hot_water
    - entity: select.my_heat_pump_operation_mode
    - entity: number.my_heat_pump_heating_curve_main_circuit
    - entity: sensor.my_heat_pump_outdoor_temperature
    - entity: sensor.my_heat_pump_supply_temperature
  ```
- **History and statistics** – operating hours are long-term statistics, so the energy dashboard-style graphs work. Add the *Last contact* sensor to a card if you want to see that the data is fresh.

## If something looks wrong

| You see | It usually means |
|---|---|
| A value does not change for hours | Thermia only uploads a value when it changes. The outdoor temperature can stand still for a day. *Last contact* tells you whether the heat pump is in touch with the cloud |
| An entity is *unavailable* | The heat pump does not report it in its current state (see section 3), or the cloud is not reachable. Check *Online* |
| Sign-in fails with a correct password | Thermia sometimes needs you to accept updated terms: sign in once at <https://online.thermia.se> and try again |
| Names are in the wrong language | *Configure → Names & language*; press *Refresh names* on the device |
| A setting cannot be changed | *Read-only mode* may be on, or the cloud reports the register as read-only |

Still stuck? Download the diagnostics (device page → *Download diagnostics*) and open an issue. The file is redacted, but have a quick look before posting.
