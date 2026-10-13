"""Phase 106: is_known_persona() match/no-match cases."""

from src.hrb_chatbot.common.known_personas import is_known_persona


def test_a_known_combo_matches():
    assert is_known_persona("EMP052", "Eddy Employee", "employee") is True


def test_full_name_match_is_case_and_whitespace_insensitive():
    assert is_known_persona("EMP052", "  eddy EMPLOYEE  ", "employee") is True


def test_unknown_employee_id_does_not_match():
    assert is_known_persona("EMP999", "Eddy Employee", "employee") is False


def test_right_employee_id_wrong_role_does_not_match():
    assert is_known_persona("EMP052", "Eddy Employee", "hr_support") is False


def test_right_employee_id_wrong_name_does_not_match():
    assert is_known_persona("EMP052", "Someone Else", "employee") is False


# Phase 147 - one real check per expanded role, not every new entry -
# is_known_persona() itself is already fully covered above; this just
# proves the new rows actually made it into the roster correctly.


def test_a_phase_147_employee_persona_matches():
    assert is_known_persona("EMP001", "John Doe", "employee") is True


def test_a_phase_147_manager_persona_matches():
    assert is_known_persona("MGR001", "Alice Johnson", "manager") is True


def test_a_phase_147_hr_support_persona_matches():
    assert is_known_persona("EMP021", "Daniel Rodriguez", "hr_support") is True


def test_a_phase_147_persona_with_the_wrong_role_does_not_match():
    # Daniel Rodriguez is a real employee, but not with the manager role.
    assert is_known_persona("EMP021", "Daniel Rodriguez", "manager") is False


# Phase 169 added the admin role here; Phase 171 moved its secret-code
# check into AdminCredentialStore (see test_admin_credential_store.py) -
# this file no longer holds any secret-code logic.
