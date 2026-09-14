# How to Submit Your Hackathon Entry

Follow these steps to set up your submission repository correctly.
The judges depend on this structure to review your entry — deviations may affect your score.

---

## Step 1 — Fork This Template

1. Click the **"Use this template"** button at the top of this repository
   (or **Fork** if you prefer)
2. Name your repository: `bob-ai-hackathon-[your-team-name]`
   (e.g., `bob-ai-hackathon-orion-squad`)
3. Set visibility to **Public** so judges can access it
4. Click **Create repository**

---

## Step 2 — Clone Your Fork Locally

```bash
git clone https://github.com/[your-org]/bob-ai-hackathon-[your-team-name].git
cd bob-ai-hackathon-[your-team-name]
```

---

## Step 3 — Fill in the Required Files

Work through these files in order:

### 3a. `submission.yaml` ← **Start here**
This is the most important file. Judges use it to get an overview of your entry.

- Open [`submission.yaml`](submission.yaml)
- Fill in **every field marked `# REQUIRED`**
- Read the inline comments — they explain what each field expects

### 3b. `README.md`
- Replace every `[placeholder in brackets]` with your actual content

### 3c. `docs/`
Fill in all four documentation files:
| File | What to write |
|---|---|
| [`docs/problem-statement.md`](docs/problem-statement.md) | The problem you're solving |
| [`docs/solution-overview.md`](docs/solution-overview.md) | How your solution works |
| [`docs/architecture.md`](docs/architecture.md) | Technical architecture diagram |
| [`docs/setup-guide.md`](docs/setup-guide.md) | Exact steps to run your project |

### 3d. `src/`
- Put all your source code inside [`src/`](src/)
- Copy [`src/.env.example`](src/.env.example) and add your environment variables to it
- **Never commit a real `.env` file** — it is already in `.gitignore`

### 3e. `demo/`
| File | What to do |
|---|---|
| [`demo/demo-video-link.txt`](demo/demo-video-link.txt) | Replace placeholder URL with your real video link |
| [`demo/live-demo-url.txt`](demo/live-demo-url.txt) | Add your deployed demo URL (or write "NOT DEPLOYED") |
| [`demo/screenshots/`](demo/screenshots/) | Add 3+ screenshots named `01-*.png`, `02-*.png`, etc. |

### 3f. `presentation/`
- Add your slide deck as [`presentation/slides.pdf`](presentation/) (preferred) or `.pptx`

---

## Step 4 — Verify Your Submission Passes Validation

Every push to your repository triggers the **Validate Submission** GitHub Action automatically.

To check manually:
1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Look for **✅ Validate Submission**
4. A green checkmark means your submission is structurally complete
5. A red X means something is missing — click the run to see what

You can also run the validation locally:
```bash
# Install yq first: https://github.com/mikefarah/yq#install
yq '.' submission.yaml   # checks YAML is valid
```

---

## Step 5 — Submit Your Repository URL

Once validation passes:

1. Copy your repository URL:
   `https://github.com/[your-org]/bob-ai-hackathon-[your-team-name]`

2. Submit it via the **official entry form** at:
   `[ORGANIZER: INSERT FORM URL HERE]`

3. **Deadline:** `[ORGANIZER: INSERT DEADLINE HERE]`

> ⚠️ Submissions after the deadline will not be reviewed.
> Changes after the deadline are not considered — make sure everything is complete before submitting.

---

## Checklist Before You Submit

- [ ] `submission.yaml` — all required fields filled
- [ ] `README.md` — no `[placeholder]` text remaining
- [ ] `docs/setup-guide.md` — someone else can run your project using these instructions
- [ ] `src/` — all source code committed (no `node_modules`, no `.env`)
- [ ] `demo/demo-video-link.txt` — real video URL (3–5 min showing the app working)
- [ ] `demo/screenshots/` — at least 3 screenshots of the running application
- [ ] `presentation/slides.pdf` — slide deck present
- [ ] GitHub Actions **✅ Validate Submission** is green
- [ ] Repository is **Public**
- [ ] Entry form submitted before the deadline

---
