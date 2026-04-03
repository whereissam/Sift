# Speaker Diarization Setup

Speaker diarization identifies different speakers in audio recordings. This is especially useful for X Spaces, podcasts, and interviews.

## Requirements

- HuggingFace account (free)
- HuggingFace access token
- ~3GB disk space for models (downloaded on first use)

## Setup Steps

### 1. Create HuggingFace Account

Go to https://huggingface.co/join and create a free account.

### 2. Accept Model License Terms + Login (ONE STEP)

The pyannote models are "gated" - you must accept their license to use them.

1. **Go to**: https://huggingface.co/pyannote/speaker-diarization-3.1
2. **Click** "Agree and access repository" (you may need to login first)
3. **Repeat for these models**:
   - https://huggingface.co/pyannote/segmentation-3.0
   - https://huggingface.co/pyannote/speaker-diarization-community-1

**Why both steps?**
- Logging in = proves WHO you are (authentication)
- Clicking "Agree" = gives you PERMISSION to download the model (authorization)

### 3. Authenticate with HuggingFace

Choose ONE of these options:

**Option A: CLI Login (Recommended - Simplest)**

```bash
huggingface-cli login
```

Paste your token when prompted. Done! No need to edit `.env`.

**Option B: Environment Variable**

1. Get token from: https://huggingface.co/settings/tokens
2. Add to `.env` file:
   ```env
   HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx
   ```

### 4. Install Dependencies

```bash
# Install both transcription AND diarization
uv sync --extra transcribe --extra diarize
```

This installs:
- `faster-whisper>=1.0.0` (transcription)
- `pyannote.audio>=3.1.0` (diarization)
- `torch>=2.0.0`

**Note:** Diarization works WITH transcription - you need both extras.

### 5. Verify Setup

Start the API and check health:

```bash
uv run sift-api
```

```bash
curl http://localhost:8000/api/health | jq
```

Look for:
```json
{
  "diarization_available": true
}
```

## Usage

### Via API

```bash
# Transcribe with speaker diarization
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=xxx",
    "diarize": true,
    "output_format": "dialogue"
  }'
```

### Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `diarize` | bool | `false` | Enable speaker diarization |
| `num_speakers` | int | `null` | Exact number of speakers (improves accuracy if known) |
| `output_format` | string | `text` | Output format: `text`, `srt`, `vtt`, `json`, `dialogue` |

### Output Formats with Diarization

**dialogue** - Best for reading:
```
SPEAKER_00: Hello everyone, welcome to the show.
SPEAKER_01: Thanks for having me.
SPEAKER_00: Let's dive right in.
```

**srt** - Subtitles with speaker labels:
```
1
00:00:01,000 --> 00:00:03,500
[SPEAKER_00] Hello everyone, welcome to the show.

2
00:00:03,500 --> 00:00:05,000
[SPEAKER_01] Thanks for having me.
```

**json** - Structured data:
```json
{
  "segments": [
    {"start": 1.0, "end": 3.5, "text": "Hello everyone", "speaker": "SPEAKER_00"},
    {"start": 3.5, "end": 5.0, "text": "Thanks for having me", "speaker": "SPEAKER_01"}
  ]
}
```

## Performance Notes

- **First run**: Models are downloaded (~3GB), takes several minutes
- **Subsequent runs**: Models are cached, much faster
- **GPU**: Significantly faster with CUDA GPU (auto-detected)
- **CPU**: Works but slower, especially for long audio

## HuggingFace Token & Rate Limits

**Good news:** You don't need to worry about rate limits for diarization.

### Why No Rate Limits?

The HuggingFace token is only used to **download gated models** to your machine. Once downloaded:

| Action | Where it runs | Rate limits? |
|--------|---------------|--------------|
| Model download | HuggingFace servers | One-time only |
| Transcription | Your local CPU/GPU | None |
| Diarization | Your local CPU/GPU | None |

All inference (transcription + diarization) runs **100% locally** after the initial model download. No ongoing API calls to HuggingFace.

### HuggingFace Free Tier (for reference)

If you use HuggingFace's **Inference API** (cloud-hosted models) for other projects, these limits apply:

- **Free tier**: Hourly reset limits, limited monthly credits
- **PRO ($9/month)**: 20x more monthly allowance
- **Enterprise**: Highest rate limits

But again, Sift diarization runs locally - these limits don't apply.

### Token Security

- Your token only needs **read** access (not write)
- Store it in `.env` or use `huggingface-cli login`
- Never commit tokens to git (`.env` is in `.gitignore`)

## Troubleshooting

### "401 Unauthorized" Error
- You haven't accepted the model license terms
- Go to the model pages (Step 3) and click "Agree and access repository"

### "Token required" Error
- `HUGGINGFACE_TOKEN` not set in `.env`
- Token is invalid or expired

### "pyannote not installed" Error
- Run `uv sync --extra diarize`

### Out of Memory
- Try shorter audio files
- Close other applications
- Use CPU instead of GPU (set `CUDA_VISIBLE_DEVICES=""`)
