# ========= Copyright (c) 2026 TTFISH. Licensed under the MIT License. =========
# See the LICENSE file in the project root for the full license text.
#
# SPDX-License-Identifier: MIT
# ==============================================================================
import os
import sys
from camel.logger import set_log_level

from owl.utils import run_society

from camel.societies import RolePlaying
from task import construct_society as construct_task_society

set_log_level(level="DEBUG")


def construct_society(question: str) -> RolePlaying:
    r"""Construct a society of agents based on the given question.

    Args:
        question (str): The task or question to be addressed by the society.

    Returns:
        RolePlaying: A configured society of agents ready to address the
            question.
    """

    output_dir = os.path.abspath("random_browse_output")
    os.makedirs(output_dir, exist_ok=True)
    return construct_task_society(question, output_dir)


def main():
    r"""Main function to run the OWL system with an example question."""
    # Default research question
    default_task = "Navigate to ttfish.cc, count the paper numbers has been published. No need to verify your answer."

    # Override default task if command line argument is provided
    task = sys.argv[1] if len(sys.argv) > 1 else default_task

    # Construct and run the society
    society = construct_society(task)
    try:
        answer, chat_history, token_count = run_society(society)
    finally:
        browser_toolkit = getattr(society, "_chimera_browser_toolkit", None)
        if browser_toolkit is not None:
            browser_toolkit.close()
        terminal_toolkit = getattr(society, "_chimera_terminal_toolkit", None)
        if terminal_toolkit is not None:
            terminal_toolkit.close()

    # Output the result
    print(f"\033[94mAnswer: {answer}\033[0m")


if __name__ == "__main__":
    main()
