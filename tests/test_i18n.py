"""Offline language contract, Spanish intake and existing borrower page checks."""
import ast
import json
import os
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

for key in ('CRS_USER', 'CRS_PASS', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
    os.environ.pop(key, None)

from app.main import app
from exchange import i18n, person
from exchange.intake import MandateChat, clean, parse
from test_person import session

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in ('outcome', 'severity', 'lender', 'bureau'):
                yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)


def assert_spanish(view):
    copy = ' '.join(leaves(view))
    assert not re.search(r'\b(?:your|months?|yearly|checking|lends|would|borrow|payment|collection|credit score|simulated|allowed|blocked)\b', copy, re.I), copy
    assert 'Esta consulta no afecta tu puntaje' in view['before']['soft_pull']
    assert 'meses' in view['before']['term']
    if view['deal']:
        assert all(step['simulated'] and 'Simulado' in step['text'] for step in view['deal']['on_accept'])


def test_all_person_keys_and_ui_keys_have_spanish_and_matching_parameters():
    assert set(i18n.STRINGS['en']) == set(i18n.STRINGS['es'])
    tree = ast.parse((ROOT/'exchange/person.py').read_text(encoding='utf8'))
    keys = {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == 'tr' and n.args and isinstance(n.args[0], ast.Constant)}
    keys |= {person.SOFT_PULL, person.PRIVACY}
    assert len(keys) > 100
    assert keys <= i18n.STRINGS['es'].keys()
    for key, es in i18n.STRINGS['es'].items():
        assert es.strip()
        assert set(re.findall(r'\{(\w+)\}', es)) <= set(re.findall(r'\{(\w+)\}', i18n.STRINGS['en'][key])), key


@pytest.mark.parametrize('persona', ['P01', 'P04', 'P05', 'P13', 'P17'])
def test_spanish_person_and_batch_api_have_no_english_borrower_sentences(persona):
    ex = session(persona)
    spanish = person.build(ex, lang='es')
    assert_spanish(spanish)
    assert person.build(ex) == person.build(ex, lang='en')  # no request-local language leak
    response = client.get(f'/api/exchange/{persona}?lang=es')
    assert response.status_code == 200
    assert response.json()['lang'] == 'es'
    assert_spanish(response.json()['person'])
    assert response.json()['notice'].startswith('Datos del entorno')
    for key in ('amount', 'monthly_payment', 'apr', 'fee', 'total_paid'):
        if spanish['deal']:
            assert spanish['deal'][key] == person.build(ex)['deal'][key]


@pytest.mark.parametrize('persona', ['P01', 'P04', 'P05', 'P13', 'P17'])
def test_spanish_stream_result_and_observer_summaries(persona):
    r = client.get(f'/api/exchange/{persona}/stream?lang=es&pace=0')
    assert r.status_code == 200
    packets = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
    result = next(p for p in packets if 'person' in p)
    assert_spanish(result['person'])
    assert packets[0]['lang'] == 'es'
    summaries = [p['view'] for p in packets if p.get('view')]
    assert summaries
    assert all(not re.search(r'\b(?:Checking|Allowed|Blocked|loan|borrower|lender)\b', v['what']) for v in summaries)


def test_person_attack_and_dispute_translations():
    for scenario in ('bait_switch', 'data_grab', 'injection', 'drift'):
        ex = session('P01', scenario)
        assert_spanish(person.build(ex, 'es'))
    from exchange.borrower import RuleBorrower
    from exchange.lenders import RuleLender
    from exchange.referee import Exchange
    from exchange.messages import Mandate
    from agent.sources import SampleSource
    from agent.scorecard import AS_OF
    ex = Exchange('P17', Mandate(min_amount=5000), SampleSource(),
                  [RuleLender(x) for x in ('prime_bank', 'newstart', 'second_chance')], RuleBorrower(), today=AS_OF)
    ex.run()
    view = person.build(ex, 'es')
    assert 'Pide tu informe gratuito' in view['no_deal']['bureau_dispute']['how_to_dispute']
    assert 'annualcreditreport.com' in view['no_deal']['bureau_dispute']['how_to_dispute']


def test_spanish_red_team_report_keeps_the_original_attack_evidence():
    from exchange.adversary import report
    ex = session('P01', 'red_team')
    from app.main import _views
    localized = _views(ex, lang='es')
    assert localized['red_team'] == report(ex)
    assert localized['red_team']['lender'] == 'SwiftLend Express'
    assert localized['red_team']['caught'] == localized['red_team']['tried']
    assert_spanish(localized['person'])


@pytest.mark.parametrize('text,expected', [
    ('necesito 5000 dólares; puedo pagar 200 dólares al mes, en 36 meses, sin cargos y sin pagos automáticos', (5000, 200, 36, False, 0)),
    ('Necesito 5.000,50 dólares. Pago mensual de 200,50 dólares, entre 24 y 36 meses. Acepto pagos automáticos, sin comisiones.', (5000.5, 200.5, 36, True, 0)),
    ('Un préstamo de 5 mil dólares, hasta $250 por mes durante 3 años, no quiero pagos automáticos, sin cargos.', (5000, 250, 36, False, 0)),
    ('Necesito $5,000. Pago $200 cada mes durante 2 años. Pagos automáticos sí, sin cargos.', (5000, 200, 24, True, 0)),
])
def test_common_spanish_mandates(text, expected):
    f = clean(parse([text]))
    assert tuple(f[k] for k in ('amount','max_payment','max_term','autopay','max_fee')) == expected
    r = MandateChat(client=False).turn([{'role':'user','content':text}], lang='es')
    assert r['ready'] and r['source'] == 'rules'
    assert r['reply'].startswith('Entendido:')
    assert r['mandate']['amount'] == expected[0]


def test_spanish_income_is_not_a_payment_or_loan_request_and_later_limits_win():
    f = clean(parse(['Gano 2500 dólares al mes. Necesito 1000 dólares.', 'Puedo pagar 100 dólares al mes en 24 meses.', 'Mejor 80 dólares al mes, no pagos automáticos.']))
    assert f['amount'] == 1000 and f['max_payment'] == 80 and f['autopay'] is False
    r = client.post('/api/chat/mandate', json={'lang':'es', 'messages':[{'role':'user','content':'necesito 5000 dólares'}]}).json()
    assert r['source'] == 'rules' and 'máximo al mes' in r['reply']


def test_money_and_number_formatting_is_local_and_reset():
    with i18n.language('es'):
        assert i18n.money(5000.5) == '5.000,50 USD'
        assert i18n.number(12.5) == '12,5'
    assert i18n.money(5000.5) == '$5,000.50'
    with pytest.raises(ValueError):
        person.build(session('P01'), 'xx')


def test_invalid_language_is_rejected_and_existing_pages_still_serve():
    for path in ('/api/exchange/P01?lang=xx', '/api/exchange/P01/stream?lang=xx'):
        assert client.get(path).status_code == 422
    assert client.post('/api/chat/mandate', json={'lang':'xx','messages':[]}).status_code == 422
    for path in ('/demo', '/phone', '/static/exchange.html', '/exchange', '/borrower'):
        r = client.get(path)
        assert r.status_code == 200 and 'text/html' in r.headers['content-type']
        assert '/api/i18n.js' in r.text and '/static/chat-access.js' in r.text
    catalog = client.get('/api/i18n.js')
    assert catalog.status_code == 200 and 'BORROWER_MESSAGES=' in catalog.text


def test_accessibility_hooks_are_present_on_the_chat():
    for name in ('demo.html',):
        text = (ROOT/'app/static'/name).read_text(encoding='utf8')
        assert 'aria-live="polite"' in text and 'BorrowerUI.narrationButton' in text
        assert 'BorrowerUI.lang' in text
        for raw in re.findall(r'BorrowerUI\.message\(("(?:[^"\\]|\\.)*")', text):
            assert json.loads(raw) in i18n.STRINGS['es']
    css = (ROOT/'app/static/chat-access.css').read_text()
    assert ':focus-visible' in css and 'prefers-reduced-motion' in css
