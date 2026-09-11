from tramplin.infrastructure.email_renderer import EmailRenderer


def test_renders_subject_html_and_text_with_inlined_css() -> None:
    renderer = EmailRenderer()

    rendered = renderer.render("otp", {"code": "482913", "ttl_minutes": 10})

    assert rendered.subject == "Код для входа: 482913"
    assert "482913" in rendered.html
    assert "482913" in rendered.text
    # premailer инлайнит правила из <head><style> в атрибут style="..."
    assert "<style>" not in rendered.html
    assert 'style="' in rendered.html
