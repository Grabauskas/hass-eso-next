def test_captures_tfa_form_fields(eso_module, fixtures_path):
    FormParser = eso_module("form_parser").FormParser
    html = (fixtures_path / "tfa_page.html").read_text(encoding="utf-8")

    parser = FormParser()
    parser.feed(html)

    assert parser.get("form_id") == "gpc_tfa_login_auth_form"
    assert parser.get("form_build_id") == "form-D9AvTpq4nDOrqtATuSxtgQzylt68ZkUCl8LbusBgApE"
    assert parser.get("action") == "/user/login/tfa/1286168/-Gern22djUGPyjorvNonwdGNVbdNRhaUI37LUXjlgsI"


def test_action_absent_when_no_form(eso_module):
    FormParser = eso_module("form_parser").FormParser
    parser = FormParser()
    parser.feed("<div>no form here</div>")
    assert parser.get("action") is None
