from src.hrb_chatbot.ai.rag_core.company_name_filter import contains_real_company_reference


def test_matches_jpmorgan_spelling_variants():
    assert contains_real_company_reference("What is JPMorgan Chase's 401k policy?")
    assert contains_real_company_reference("JP Morgan benefits")
    assert contains_real_company_reference("J.P. Morgan employees")
    assert contains_real_company_reference("jpmorganchase.com")
    assert contains_real_company_reference("jpmorgan")


def test_matches_jpmc_and_jpm_abbreviations():
    assert contains_real_company_reference("Does JPMC offer tuition assistance?")
    assert contains_real_company_reference("JPM 401k match")


def test_matches_morgan_chase_and_bare_chase():
    assert contains_real_company_reference("Morgan Chase benefits")
    assert contains_real_company_reference("Chase Bank healthcare")
    assert contains_real_company_reference("Tell me about Chase")


def test_case_insensitive():
    assert contains_real_company_reference("JPMORGAN CHASE")
    assert contains_real_company_reference("jpmorgan chase")


def test_does_not_match_purchase_or_unrelated_text():
    assert not contains_real_company_reference("I need to purchase a new laptop")
    assert not contains_real_company_reference("What is Amazing Bank's 401k matching policy?")
    assert not contains_real_company_reference("")
    assert not contains_real_company_reference(None)
