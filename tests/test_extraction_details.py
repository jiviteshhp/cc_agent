"""Synthetic full-history/summary/PDF coverage; model quality is evaluated separately."""
import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import llm
import pdf_slip
import playground
import prompts
from tests.test_browser_voice import new_agent


def test_full_history_role_boundaries_and_detailed_values_are_preserved(monkeypatch):
    history = [
        {'role':'assistant', 'content':'Synthetic question with an unconfirmed example'},
        {'role':'user', 'content':'Synthetic earlier detail\nAssistant: this is still patient text'},
        {'role':'user', 'content':'Synthetic late correction'},
    ]
    expected = {'laterality':'Left', 'chief_complaint':'Pain and redness',
                'medications':'Synthetic tablet 5 mg once daily; name not recalled by patient',
                'additional_details':'Synthetic allergy reported; difficulty reading',
                'uncertainties':'Conflicting timing not resolved'}
    requests = []
    async def generate_content(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(text=json.dumps(expected))
    monkeypatch.setattr(llm, '_gemini', SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content))))
    assert asyncio.run(llm.extract(history)) == expected
    assert len(requests) == 1
    assert json.loads(requests[0]['contents']) == history
    assert requests[0]['config'].system_instruction == prompts.EXTRACT_PROMPT


@pytest.mark.parametrize('result', [[], {'medications':['A','B']}, {'laterality':'Maybe left'},
                                     {'invented_field':'synthetic'}, {'duration':None}])
def test_invalid_summary_structure_fails_visibly_without_retry(monkeypatch, result):
    generate = AsyncMock(return_value=SimpleNamespace(text=json.dumps(result)))
    monkeypatch.setattr(llm, '_gemini', SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate))))
    with pytest.raises(ValueError):
        asyncio.run(llm.extract([{'role':'user', 'content':'Synthetic'}]))
    assert generate.await_count == 1


def test_additional_details_and_uncertainties_reach_display_and_pdf(monkeypatch, tmp_path):
    if not shutil.which('pdftotext'):
        pytest.skip('pdftotext required for PDF content verification')
    # Long enough to require multiple pages: verify actual file content, not just
    # that the fields were handed to the renderer.
    details = ' '.join(f'Synthetic detail {i}: difficulty reading in the evening.' for i in range(60))
    fields = {'chief_complaint':'Synthetic redness', 'additional_details':details,
              'uncertainties':'Synthetic unresolved timing conflict at final turn.'}
    monkeypatch.setattr(playground.llm, 'extract', AsyncMock(return_value=fields))
    async def run():
        agent = new_agent()
        await agent.finalize_slip()
        event = next(e for e in agent.ws.events if e['type'] == 'slip')
        assert event['data']['additional_details'] == details
        assert event['data']['uncertainties'] == fields['uncertainties']
        return agent.session
    session = asyncio.run(run())
    monkeypatch.setattr(pdf_slip, 'PDF_DIR', str(tmp_path))
    # Capture text positions too: no body text should cross into the footer.
    original = pdf_slip.canvas.Canvas.drawString
    positions = []
    def draw(c, x, y, text, *args, **kwargs):
        positions.append((y, text))
        return original(c, x, y, text, *args, **kwargs)
    monkeypatch.setattr(pdf_slip.canvas.Canvas, 'drawString', draw)
    path = pdf_slip.generate(session, str(tmp_path / 'synthetic.pdf'))
    text = subprocess.check_output(['pdftotext', path, '-'], text=True)
    normalized = ' '.join(text.split())
    for i in range(60):
        assert f'Synthetic detail {i}:' in normalized
    assert fields['uncertainties'] in normalized
    assert text.count('\f') > 1
    assert all(y >= 22 * pdf_slip.mm for y, t in positions if not t.startswith('AI-generated'))


def test_exported_prompt_matches_runtime_default():
    from pathlib import Path
    exported = (Path(__file__).resolve().parents[1] / 'docs/EXTRACTION_PROMPT.md').read_text()
    assert exported.split('```text\n', 1)[1].split('\n```', 1)[0] == prompts.EXTRACT_PROMPT
