# models/

This directory stores all **model artefacts** used by AetheerAI.

```
models/
├── trained/        Pre-trained or fine-tuned model weights (.bin, .safetensors, .gguf)
├── configs/        Model configuration files (tokenizer configs, model cards, YAML specs)
└── checkpoints/    Training checkpoints (resumable mid-train snapshots)
```

## Usage

| Sub-directory  | What goes here                                   | Checked-in to git? |
|----------------|--------------------------------------------------|--------------------|
| `trained/`     | Final model weights                              | No — add to .gitignore (too large) |
| `configs/`     | `model_config.yaml`, tokenizer JSON, etc.        | Yes                |
| `checkpoints/` | Epoch snapshots, best-model saves                | No — add to .gitignore |

## Hosting large files

Use [Git LFS](https://git-lfs.github.com/) for files > 100 MB, or store weights on an
external registry (HuggingFace Hub, S3, GCS) and record the download URL in `configs/`.
