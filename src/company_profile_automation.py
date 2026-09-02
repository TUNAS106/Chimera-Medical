# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import os
import json

import config
from foundation_model import run_llm

from dotenv import load_dotenv

env_path = config.env_path
load_dotenv()


def count_employees(company_profile):
    """Return the sum of all role counts in a generated company profile."""

    if isinstance(company_profile, dict):
        total = 0
        for key, value in company_profile.items():
            if key == "roles" and isinstance(value, list):
                total += sum(int(role.get("count", 0)) for role in value)
            else:
                total += count_employees(value)
        return total
    if isinstance(company_profile, list):
        return sum(count_employees(item) for item in company_profile)
    return 0


def generate_company_profile():
    json_path = config.company_config_path

    # check whether the json_path exists
    if os.path.exists(json_path):
        print(f"[WARNING] The team json {json_path} already exists.")
        return

    previous_error = ""
    for attempt in range(config.max_attempt):
        system_prompt = """"You are an expert project and team planner.
                                The user will provide you with the company size (employee number) and the project goal to finish within a certain time.
                                You will help in generating the role profile for the company/institution to achieve the goal.
                                You should include the roles of the team, the number of employees for each role, and whether these roles are outsourced.
                                Then you should include the responsibilities for each role in the company. Here is one example:\n\n
                                The goal of the company is to construct a Third-person shooter game from the beginning.
                                The size of the company is 15 people. The duration is one month. The role profile is as follows:\n\n
                                ```json\n{\n    \"core_development_team\": {\n        \"programming_team\": {\n          \"roles\": [\n            {\n              \"role_name\": \"Lead Programmer\",\n              \"abbr\": \"lpro\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Design core technical architecture\",\n                \"Implement game logic/physics engine\",\n                \"Optimize network synchronization\"\n              ]\n            },\n            {\n              \"role_name\": \"Client Developers\",\n              \"abbr\": \"cdev\",\n              \"count\": 3,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Third-person camera controller\",\n                \"Character animation system\",\n                \"Weapon mechanics & ballistics\"\n              ]\n            },\n            {\n              \"role_name\": \"Server Developer\",\n              \"abbr\": \"sdev\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Multiplayer matchmaking system\",\n                \"Anti-cheat implementation\",\n                \"Cloud data management\"\n              ]\n            },\n            {\n              \"role_name\": \"Tools Developer\",\n              \"abbr\": \"tdev\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Build pipeline automation tools\",\n                \"Create level editor extensions\",\n                \"Asset import pipeline optimization\"\n              ]\n            }\n          ]\n        },\n        \"design_team\": {\n          \"roles\": [\n            {\n              \"role_name\": \"Lead Game Designer\",\n              \"abbr\": \"ldes\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Core gameplay loop design\",\n                \"Combat system balancing\",\n                \"Cross-department coordination\"\n              ]\n            },\n            {\n              \"role_name\": \"Systems Designer\",\n              \"abbr\": \"sdes\",\n              \"count\": 2,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Cover system implementation\",\n                \"Enemy AI behavior trees\",\n                \"Progression system tuning\"\n              ]\n            },\n            {\n              \"role_name\": \"Narrative Designer\",\n              \"abbr\": \"ndes\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Worldbuilding documentation\",\n                \"Scriptwriting & dialogue\",\n                \"Lore integration with art assets\"\n              ]\n            }\n          ]\n        },\n        \"art_team\": {\n          \"roles\": [\n            {\n              \"role_name\": \"Concept Artist\",\n              \"abbr\": \"cart\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Character/enemy concept art\",\n                \"Environment keyframe illustrations\",\n                \"Art style guidelines\"\n              ]\n            },\n            {\n              \"role_name\": \"3D Modeler/Animator\",\n              \"abbr\": \"3dmod\",\n              \"count\": 2,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"High-poly asset modeling\",\n                \"Rigging & skinning\",\n                \"Third-person locomotion cycles\"\n              ]\n            },\n            {\n              \"role_name\": \"Technical Artist\",\n              \"abbr\": \"tart\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"Shader graph development\",\n                \"Render pipeline optimization\",\n                \"Physics-driven destruction FX\"\n              ]\n            },\n            {\n              \"role_name\": \"UI/UX Designer\",\n              \"abbr\": \"uiux\",\n              \"count\": 1,\n              \"outsource\": 0,\n              \"responsibilities\": [\n                \"HUD layout design\",\n                \"Cross-platform input mapping\",\n                \"Diegetic interface integration\"\n              ]\n            }\n          ]\n        }\n      },\n      \"support_teams\": {\n        \"roles\": [\n          {\n            \"role_name\": \"Audio Engineer\",\n            \"abbr\": \"aud\",\n            \"count\": 1,\n            \"outsource\": 1,\n            \"responsibilities\": [\n              \"Weapon SFX design\",\n              \"Dynamic music system\",\n              \"Spatial audio implementation\"\n            ]\n          },\n          {\n            \"role_name\": \"QA Testers\",\n            \"abbr\": \"qtest\",\n            \"count\": 2,\n            \"outsource\": 1,\n            \"responsibilities\": [\n              \"Combat feel iteration\",\n              \"Camera collision testing\",\n              \"Multiplayer stress tests\"\n            ]\n          },\n          {\n            \"role_name\": \"Producer\",\n            \"abbr\": \"prod\",\n            \"count\": 1,\n            \"outsource\": 0,\n            \"responsibilities\": [\n              \"Agile sprint planning\",\n              \"Resource dependency mapping\",\n              \"Risk mitigation strategies\"\n            ]\n          },\n          {\n            \"role_name\": \"Build Engineer\",\n            \"abbr\": \"being\",\n            \"count\": 1,\n            \"outsource\": 0,\n            \"responsibilities\": [\n              \"CI/CD pipeline management\",\n              \"Asset bundle optimization\",\n              \"Version control governance\"\n            ]\n          }\n        ]\n      }\n    }\n```\nNow you will take the input company size and the task goal from the user, and return only the JSON format of the role profile for the company."
        """
        # The legacy 15-person example above tends to make smaller models add
        # plausible but unrequested roles. Replace it with an explicit cardinality
        # contract before sending the request to the model.
        system_prompt = f"""You are a strict JSON company-structure generator.
Return exactly one valid JSON object, without Markdown or explanatory text.

Create exactly {config.employee_number} role objects across all arrays named
\"roles\". Every role object must have \"count\": 1, so the sum of every
\"count\" in the complete JSON tree is exactly {config.employee_number}.
Outsourced roles are included in this total. Do not add advisory, support,
management, or outsourced roles beyond the {config.employee_number} requested
role objects.

Each role object must contain:
- \"role_name\": a realistic role name
- \"abbr\": a unique lowercase ASCII abbreviation
- \"count\": 1
- \"outsource\": either 0 or 1
- \"responsibilities\": a non-empty array of strings

You may group the role objects into nested teams, but before responding, count
all role objects and verify that there are exactly {config.employee_number}.
"""
        retry_instruction = (
            f"\nThe previous response failed validation: {previous_error} "
            "Return a corrected new JSON object.\n"
            if previous_error
            else ""
        )
        user_prompt = f"""Company type: {config.company_type}
Goal: {config.goal}
Duration: {config.period} weeks
Required employee count: exactly {config.employee_number}
Required role-object count: exactly {config.employee_number}, each with count 1.
{retry_instruction}"""
        llm_output = run_llm(
            system_prompt, user_prompt, operation="company_profile_generation"
        )
        json_str = llm_output

        # remove the prefix "```json" and suffix "```"
        if "```json" in json_str:
            json_str = json_str.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(json_str)
            generated_employee_count = count_employees(data)
            if generated_employee_count != config.employee_number:
                raise ValueError(
                    "Generated company has "
                    f"{generated_employee_count} employees; expected "
                    f"{config.employee_number}."
                )
            break
        except Exception as e:
            print("[WARN] Error parsing JSON:", e, "Retrying...")
            previous_error = str(e)
            if attempt == config.max_attempt - 1:
                print("[Error] Max attempts reached. Exiting.")
                print(f"### Errored JSON ### : {json_str}")
                raise e

    # save the JSON to output/meeting_schedule.json
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(os.path.join(json_path), "w") as f:
        json.dump(data, f, indent=4)


if __name__ == "__main__":
    generate_company_profile()
