import itertools
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import config
import daily_execution_auto
import daily_execution_auto_attack
from daily_plan_update import ScheduleValidationError, parse_and_validate_schedule
from workday_policy import (
    EMAIL_REPLY_DEPTH_KEY,
    activity_validation_errors,
    bounded_pending_tasks,
    is_email_only_activity,
    mentioned_member_ids,
    parse_clock_time,
    reply_allowed,
    reply_metadata,
)


class WorkdayPolicyTests(unittest.TestCase):
    def test_reply_chain_stops_after_one_reply(self):
        origin = {"from": "ehr-1", "subject": "Status", "content": "Update"}
        self.assertTrue(reply_allowed(origin, 1))
        reply = {**origin, **reply_metadata(origin)}
        self.assertEqual(reply[EMAIL_REPLY_DEPTH_KEY], 1)
        self.assertFalse(reply_allowed(reply, 1))

    def test_pending_replan_is_strictly_inside_workday(self):
        current = parse_clock_time("17:30:00")
        end = parse_clock_time("18:00:00")
        proposal = [
            {"Time": "17:30:00", "Activity": "past boundary"},
            {"Time": "17:45:00", "Activity": "valid"},
            {"Time": "18:00:00", "Activity": "cutoff"},
            {"Time": "20:00:00", "Activity": "after hours"},
        ]
        self.assertEqual(
            bounded_pending_tasks(proposal, current, end), [proposal[1]]
        )

    def test_schedule_validator_rejects_cutoff_and_after_hours(self):
        valid = json.dumps([{"Time": "17:59", "Activity": "Wrap up"}])
        self.assertEqual(
            parse_and_validate_schedule(valid)[0]["Time"], "17:59:00"
        )
        for invalid_time in (config.workday_end, "20:00"):
            with self.subTest(invalid_time=invalid_time):
                invalid = json.dumps(
                    [{"Time": invalid_time, "Activity": "Too late"}]
                )
                with self.assertRaises(ScheduleValidationError):
                    parse_and_validate_schedule(invalid)

    def test_schedule_validator_rejects_before_workday(self):
        invalid = json.dumps(
            [{"Time": "07:59", "Activity": "Too early"}]
        )
        with self.assertRaises(ScheduleValidationError):
            parse_and_validate_schedule(invalid)

    def test_activity_classification_preserves_compound_work(self):
        email = "Email @data-1 to request the schema"
        compound = "Create the report and email @data-1 with findings"
        self.assertTrue(is_email_only_activity(email))
        self.assertFalse(is_email_only_activity(compound))
        self.assertEqual(mentioned_member_ids(compound), ["data-1"])

    def test_activity_mentions_reject_placeholder_self_and_unknown(self):
        errors = activity_validation_errors(
            "Email @PEOPLE, @it-1 and @ghost-1",
            "it-1",
            {"it-1", "data-1"},
        )
        self.assertEqual(len(errors), 3)

    def test_member_blocks_reply_to_reply_before_model_call(self):
        member = daily_execution_auto.Member.__new__(
            daily_execution_auto.Member
        )
        member.id = "it-1"
        member._task_id_seq = itertools.count()
        member.email_reply_count = 0
        logged = []
        member.schedule_logging = lambda *args: logged.append(args)
        incoming = {
            "from": "influenza-1",
            "subject": "Re: Status",
            "content": "Acknowledged",
            EMAIL_REPLY_DEPTH_KEY: 1,
        }
        with patch.object(
            daily_execution_auto,
            "reply_email_content",
            side_effect=AssertionError("model must not be called"),
        ):
            member.reply_email(incoming, datetime.strptime("17:00", "%H:%M"))
        self.assertEqual(len(logged), 1)

    def test_attack_member_uses_the_same_reply_limit(self):
        member = daily_execution_auto_attack.Member.__new__(
            daily_execution_auto_attack.Member
        )
        member.id = "it-1"
        member._task_id_seq = itertools.count()
        member.email_reply_count = 0
        logged = []
        member.schedule_logging = lambda *args, **kwargs: logged.append(
            (args, kwargs)
        )
        incoming = {
            "from": "influenza-1",
            "subject": "Re: Status",
            "content": "Acknowledged",
            EMAIL_REPLY_DEPTH_KEY: 1,
        }
        with patch.object(
            daily_execution_auto_attack,
            "reply_email_content",
            side_effect=AssertionError("model must not be called"),
        ):
            member.reply_email(incoming, datetime.strptime("17:00", "%H:%M"))
        self.assertEqual(len(logged), 1)


if __name__ == "__main__":
    unittest.main()
