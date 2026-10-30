"""Generate only fictional intake source clips; never reads saved calls."""
import argparse
import asyncio
import json
from pathlib import Path
import shutil
import tempfile
from prepare_recovery_audio import prepare_clips, ROOT

async def prepare(provider):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    fixture=ROOT/'fixtures'/'care'
    turns=json.loads((fixture/'episode.json').read_text())['intake']['turns']
    destination=fixture/'audio'
    destination.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='care-intake-audio-') as staging:
        await prepare_clips(provider,{t['id']:t['text'] for t in turns},Path(staging))
        for path in Path(staging).iterdir():
            shutil.copyfile(path,destination/path.name)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--provider',choices=['sarvam','espeak'],required=True)
    asyncio.run(prepare(parser.parse_args().provider))
