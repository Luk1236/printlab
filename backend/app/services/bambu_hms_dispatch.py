"""HMS-Fehler-Aktionen über MQTT an den Bambu-Lab-Drucker senden.

Ausgelagert aus ``backend.app.services.bambu_mqtt``, damit ``bambu_mqtt.py``
kompakt und unterhalb des Dateigrößen-Budgets bleibt.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.services.hms_actions import HMSAction

logger = logging.getLogger(__name__)


def dispatch_hms_action(
    client_owner: Any,
    print_error: str,
    action: str,
    job_id: str | None = None,
) -> bool:
    """Dispatch the user's choice from the HMS-error modal as a printer command."""
    if not client_owner._client or not client_owner.state.connected:
        logger.warning("[%s] Cannot execute HMS action: not connected", client_owner.serial_number)
        return False

    def publish(payload: dict) -> None:
        client_owner._client.publish(client_owner.topic_publish, json.dumps(payload), qos=1)
        client_owner._client.publish(
            client_owner.topic_publish,
            json.dumps({"pushing": {"command": "pushall", "sequence_id": "0"}}),
            qos=1,
        )

    try:
        err_decimal = str(int(print_error, 16))
    except ValueError:
        err_decimal = print_error

    def hms_resume() -> None:
        publish({"print": {"command": "resume", "param": "", "sequence_id": "0"}})

    def hms_stop() -> None:
        publish({"print": {"command": "stop", "param": "", "sequence_id": "0"}})

    def hms_ignore_command() -> None:
        publish(
            {
                "print": {
                    "command": "ignore",
                    "err": err_decimal,
                    "param": "reserve",
                    "job_id": job_id or "",
                    "sequence_id": "0",
                }
            }
        )

    def hms_idle_ignore(persistent: bool = False) -> None:
        publish(
            {
                "print": {
                    "command": "idle_ignore",
                    "err": err_decimal,
                    "type": 1 if persistent else 0,
                    "sequence_id": "0",
                }
            }
        )

    def ams_control(param: str) -> None:
        publish({"print": {"command": "ams_control", "param": param, "sequence_id": "0"}})

    def clean_print_error() -> None:
        publish({"print": {"command": "clean_print_error", "sequence_id": "0"}})

    def uiop_close() -> None:
        publish(
            {
                "system": {
                    "command": "uiop",
                    "name": "print_error",
                    "action": "close",
                    "source": 1,
                    "type": "dialog",
                    "err": print_error.upper(),
                    "sequence_id": "0",
                }
            }
        )

    match action:
        case (
            HMSAction.RESUME_PRINTING
            | HMSAction.RESUME_PRINTING_DEFECTS
            | HMSAction.RESUME_PRINTING_PROBELM_SOLVED
            | HMSAction.PROBLEM_SOLVED_RESUME
            | HMSAction.FILAMENT_LOAD_RESUME
            | HMSAction.PROCEED
        ):
            hms_resume()

        case HMSAction.STOP_PRINTING:
            hms_stop()

        case HMSAction.IGNORE_RESUME | HMSAction.IGNORE_NO_REMINDER_NEXT_TIME | HMSAction.DONT_REMIND_NEXT_TIME:
            hms_ignore_command()

        case HMSAction.NO_REMINDER_NEXT_TIME:
            hms_idle_ignore(persistent=False)

        case HMSAction.FILAMENT_EXTRUDED | HMSAction.DBL_CHECK_DONE:
            ams_control("done")

        case (
            HMSAction.RETRY_FILAMENT_EXTRUDED
            | HMSAction.CONTINUE
            | HMSAction.RETRY_PROBLEM_SOLVED
            | HMSAction.DBL_CHECK_RETRY
        ):
            ams_control("resume")

        case HMSAction.ABORT:
            ams_control("abort")

        case HMSAction.OK_BUTTON:
            clean_print_error()

        case HMSAction.DBL_CHECK_OK:
            clean_print_error()
            uiop_close()

        case HMSAction.DBL_CHECK_RESUME:
            publish({"print": {"command": "resume", "param": "", "sequence_id": "0"}})

        case HMSAction.REFRESH_NOZZLE:
            publish({"print": {"command": "refresh_nozzle", "sequence_id": "0"}})

        case HMSAction.TURN_OFF_FIRE_ALARM:
            publish({"print": {"command": "buzzer_ctrl", "mode": 0, "sequence_id": "0"}})

        case HMSAction.STOP_DRYING:
            publish({"print": {"command": "auto_stop_ams_dry", "sequence_id": "0"}})

        case HMSAction.DISABLE_PURIFICATION:
            publish({"print": {"command": "close_air_filt", "sequence_id": "0"}})

        case (
            HMSAction.CHECK_ASSISTANT
            | HMSAction.JUMP_TO_LIVEVIEW
            | HMSAction.OK_JUMP_RACK
            | HMSAction.REMOVE_CLOSE_BTN
            | HMSAction.LOAD_VIRTUAL_TRAY
            | HMSAction.CANCLE
            | HMSAction.DBL_CHECK_CANCEL
        ):
            pass

        case _:
            logger.warning("[%s] Unknown HMS action '%s'", client_owner.serial_number, action)
            return False

    return True
