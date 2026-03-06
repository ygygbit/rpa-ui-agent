# App Guidebook: Security Foundations: Secure on the Go | Viva Learning

*Curated from exploration on 2026-03-07*

---

## High-Level Map

### Course Structure

This is a Viva Learning training course with **5 sections**, each containing lessons with video content. Progression is **gated** — you must complete each lesson/section before the next unlocks.

### Sections
1. **Section 1 - Welcome** (3 lessons: intro, "Why this training?", "Meeting you where you are")
2. **Section 2 - Test-out assessment** (quiz/assessment)
3. **Section 3 - Security is a shared priority** (learning content)
4. **Section 4 - Secure travel** (learning content)
5. **Section 5 - Secure your home network** (learning content)

### Navigation Flow
```
Browser → Viva Learning → My Learning > In Progress → Course Detail → Open → Loading → Play → Player
                                                                                                ↓
                                              ← NEXT (wait for video!) → Next Lesson/Section → ...
```

---

## CRITICAL: Video Wait Strategy

**Videos take 1-5 REAL minutes to play.** The NEXT button stays DISABLED until the video finishes. You MUST:

1. Click Play if video hasn't started (play button at ~347, 790 or center of video area)
2. Use `{"type": "wait", "seconds": 90}` to wait for the video to play through (90s covers most lessons)
3. Take a screenshot to check if NEXT button is now enabled
4. **AFTER WAITING: Look at the BOTTOM-RIGHT of the player controls (~1518, 790). Is NEXT bright/enabled? If YES → click NEXT immediately. Do NOT click Play again.**
5. If NEXT is still disabled, wait another 90 seconds: `{"type": "wait", "seconds": 90}`
6. Repeat wait → screenshot → check NEXT cycle until NEXT enables (usually 1-2 wait cycles)
7. ONLY click NEXT when it appears enabled/clickable (not grayed out)

**DO NOT** rapidly click NEXT or skip ahead — it won't work.
**DO NOT** click Play after waiting — the video already finished. Check NEXT first!

**BE EFFICIENT**: Batch actions in one turn when possible. For example:
`[{"type": "click", "x": 347, "y": 790}, {"type": "wait", "seconds": 90}, {"type": "screenshot"}]`
This does Play + Wait + Check in a single turn instead of three. Patience is required.

---

## General Patterns (How Viva Learning Courses Work)

### Completing a Lesson
1. Video auto-plays or click Play to start
2. **WAIT 90 SECONDS** for video to finish — use `{"type": "wait", "seconds": 90}`
3. Take screenshot to check NEXT button state at bottom-right (~1518, 790)
4. **If NEXT is enabled (bright, not grayed out), CLICK NEXT at (1518, 790). Do NOT click Play again.**
5. If NEXT is still disabled, wait another 90 seconds and check again
6. If a lesson has interactive elements (quiz, clickable items), complete them before NEXT enables
7. **NEVER click Play after a wait — the video is done. Always check NEXT first.**
8. **Batch your actions**: `[click Play, wait 90s, screenshot]` in ONE turn to be efficient.

### Section Progression
- Sections are listed in the left sidebar under MENU tab
- Locked sections show a padlock icon
- Completed lessons show a checkmark
- Active/current lesson is highlighted
- Complete all lessons in a section → next section unlocks

### Key UI Elements
- **NEXT button**: Bottom-right of player controls at approximately (1518, 790). **Disabled** during playback, **enabled** after completion.
- **Play/Pause**: Bottom-left at approximately (347, 790)
- **MENU tab**: Left sidebar at approximately (80, 371) — shows course outline
- **TRANSCRIPT tab**: Left sidebar at approximately (145, 371)
- **RESOURCES tab**: Left sidebar at approximately (230, 371)
- **Close button**: Top-right at approximately (1512, 154) — returns to course detail
- **Playback timeline**: Progress bar at approximately (860, 790) — check progress visually

### How to Tell If NEXT Is Enabled
- **Enabled**: NEXT text/button appears bright/solid, cursor changes on hover
- **Disabled**: NEXT text appears grayed out, dimmed, or has no hover effect
- Check the playback timeline — if it's at the end (fully filled), NEXT should be enabled

### Troubleshooting
- "Content not playing properly" modal → dismiss it (click X or OK) and try again
- If playback doesn't start → click the Play button (center of video area or at ~347, 790)
- If NEXT stays disabled after 3+ minutes → check for interactive elements (quiz, clickable items) that need completion first
- The course player is embedded in Viva Learning's shell — use the Close button (not browser back) to return

---

## Low-Level Map: Course Player

### Player Layout (1600x900 viewport)

```
+------------------------------------------------------------------+
| [Viva Learning logo] [Home] [My Learning] [Academies] [Manage]  |
|  Viva Learning > Security Foundations: Secure on the Go  [X Close]|
+------------------------------------------------------------------+
|                    |                                              |
| [Microsoft Logo]   |  Security Foundations: Secure on the Go     |
|                    |                                              |
| [MENU][TRANSCRIPT] |                                              |
| [RESOURCES]        |        VIDEO / CONTENT AREA                  |
|                    |                                              |
| Section 1 - Welcome|                                              |
|  ✓ Intro lesson    |                                              |
|  🔒 Why training?  |                                              |
|  🔒 Meeting you... |                                              |
| Section 2 🔒       |                                              |
| Section 3 🔒       |                                              |
| Section 4 🔒       |                                              |
| Section 5 🔒       |                                              |
|                    |  [Play] [=====timeline=====] [Vol][CC][⛶][NEXT]|
+------------------------------------------------------------------+
```

### Step-by-Step Workflow to Complete the Course

1. Open Edge/Chrome browser
2. Navigate to Viva Learning: use Ctrl+L, type "viva learning", Enter
3. Go to My Learning > In Progress tab
4. Find "Security Foundations: Secure on the Go" and click it
5. Click "Open" or "Play" on the course detail page
6. Wait for loading spinner to finish
7. Click Play on the start screen (large play button in center)
8. **FOR EACH LESSON/SECTION repeat this cycle:**
   a. Ensure video is playing (if paused, click Play at ~347, 790)
   b. Wait 90 seconds: `{"type": "wait", "seconds": 90}` — **batch with click in same turn**
   c. Take screenshot — **FIRST check NEXT button (bottom-right ~1518, 790): is it bright/enabled?**
   d. If NEXT is enabled → click NEXT at (1518, 790). **Do NOT click Play again.**
   e. If NEXT still disabled → wait another 90 seconds, screenshot, check NEXT again
   f. If quiz/interactive content appears → answer questions, click Submit
   g. Continue to next lesson
9. After Section 5 is complete, the course shows as Completed

### Important Notes
- Do NOT click Close/Back during a lesson — it may lose progress
- The NEXT button position is consistent: bottom-right of the player controls
- Some lessons may have quizzes — look for radio buttons, checkboxes, or "Submit" buttons
- Videos typically last 1-5 minutes per lesson
- Section 2 (Test-out assessment) has multiple-choice questions — read and answer them
- TOTAL estimated time: 15-30 minutes due to video playback waits
