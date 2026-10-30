"""Bounded PCM prefetch and safe incremental text, shared by both call paths."""
import asyncio
import unicodedata
from contextlib import aclosing


async def speech_text(chunks):
    """Strip split control markers; preserve word spacing across LLM chunks.

    Never send whitespace-only messages or more than 500 characters per message.
    Hindi combining marks and joiners are retained. No patient text is logged.
    """
    pending = ""
    async with aclosing(chunks):
        async for text in chunks:
            if not isinstance(text, str):
                raise ValueError("Speech text must be a string")
            text = ''.join(' ' if ch in '\n\r\t' else ch for ch in text
                           if ch in '\n\r\t' or unicodedata.category(ch) not in ('Cc', 'Cs'))
            pending = (pending + text).replace('<END>', '')
            hold = next((n for n in range(min(4, len(pending)), 0, -1)
                         if pending.endswith('<END>'[:n])), 0)
            visible = pending[:-hold] if hold else pending
            suffix = pending[-hold:] if hold else ''
            if visible.strip():
                # Keep trailing whitespace to attach to the next nonempty token.
                ready = visible.rstrip()
                pending = visible[len(ready):] + suffix
                for offset in range(0, len(ready), 500):
                    part = ready[offset:offset + 500]
                    if part.strip():
                        yield part
                    else:
                        pending = part + pending
            else:
                pending = visible + suffix
            if len(pending) > 1000:
                pending = ' ' + suffix  # bound an arbitrarily long whitespace run
    if pending.strip() and not '<END>'.startswith(pending.strip()):
        yield pending


async def prefetch_pcm(source, sample_rate, seconds=1.0):
    """Read ahead at most one second, in <=100 ms pieces; cancel on consumer exit."""
    block = sample_rate * 2 // 10
    queue = asyncio.Queue(maxsize=max(1, int(seconds * 10)))

    async def produce():
        error = None
        try:
            async with aclosing(source):
                async for pcm in source:
                    if len(pcm) % 2:
                        raise ValueError('Incomplete PCM sample')
                    for offset in range(0, len(pcm), block):
                        await queue.put(pcm[offset:offset + block])
        except Exception as exc:
            error = exc
        await queue.put(None)
        if error is not None:
            raise error

    producer = asyncio.create_task(produce())
    try:
        while True:
            pcm = await queue.get()
            if pcm is None:
                await producer
                return
            yield pcm
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
