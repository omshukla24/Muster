"""
Unit tests for CALL-E client integration and Mock harness.
"""

import pytest
import os
from muster.calle_client import CalleClient, MockCalleClient


def test_calle_client_environment_attribution():
    client = CalleClient(
        source="skills_sh",
        integration="skills_sh_skill",
        integration_version="0.1.0"
    )
    env = client._get_env()
    assert env["CALLE_SOURCE"] == "skills_sh"
    assert env["CALLE_INTEGRATION"] == "skills_sh_skill"
    assert env["CALLE_INTEGRATION_VERSION"] == "0.1.0"


@pytest.mark.asyncio
async def test_mock_calle_client_scenarios():
    mock = MockCalleClient(artificial_delay_sec=0.0)

    # 1. Present Scenario
    res_pres = await mock.execute_call_audit(
        phone="+919876543201",
        goal="Verification goal",
        mock_scenario="PRESENT",
        entity_name="Apollo Hospital"
    )
    assert res_pres["status"] == "COMPLETED"
    assert res_pres["extracted"]["reached_human"] is True
    assert res_pres["extracted"]["accepts_scheme"] is True
    assert len(res_pres["evidence"]) > 0

    # 2. Ghost Refused
    res_ghost = await mock.execute_call_audit(
        phone="+919876543202",
        goal="Verification goal",
        mock_scenario="GHOST_REFUSED",
        entity_name="Care Hospital"
    )
    assert res_ghost["extracted"]["accepts_scheme"] is False
    assert res_ghost["extracted"]["operating_status"] == "left_scheme"

    # 3. Dead Line
    res_dead = await mock.execute_call_audit(
        phone="+919876543200",
        goal="Verification goal",
        mock_scenario="GHOST_DEAD_LINE"
    )
    assert res_dead["status"] == "FAILED"
    assert "does not exist" in res_dead["transcript"]

    # 4. No Answer
    res_unreach = await mock.execute_call_audit(
        phone="+919876543203",
        goal="Verification goal",
        mock_scenario="UNREACHABLE_NO_ANSWER"
    )
    assert res_unreach["status"] == "NO ANSWER"
