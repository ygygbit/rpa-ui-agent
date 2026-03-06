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

### Key Pages

| Page | Description | How to Reach |
|------|-------------|-------------|
| course_detail | Course overview with Open/Play button | Search "Secure on the Go" in Viva Learning or navigate from My Learning > In Progress |
| playback_loading | Loading spinner before content loads | Click "Open" on course detail page |
| playback_start | Start screen with large Play button | Wait for loading to finish |
| player_menu | Main player with sidebar menu, video, NEXT button | Click Play on start screen |
| player_transcript | Transcript tab view | Click TRANSCRIPT tab in sidebar |
| player_resources | Resources/links tab view | Click RESOURCES tab in sidebar |

### Navigation Flow
```
Browser → Search → Course Detail → Open → Loading → Start Screen → Player
                                                                      ↓
                                        ← NEXT button → Next Lesson/Section
```

---

## General Patterns (How Viva Learning Courses Work)

### Completing a Lesson
1. Video auto-plays or click Play to start
2. Wait for video to finish (NEXT button is disabled during playback)
3. When video completes, NEXT button becomes enabled
4. Click NEXT to advance to the next lesson
5. If a lesson has interactive elements (quiz, click items), complete them before NEXT enables

### Section Progression
- Sections are listed in the left sidebar under MENU tab
- Locked sections show a padlock icon
- Completed lessons show a checkmark icon
- Active/current lesson is highlighted
- Complete all lessons in a section → next section unlocks

### Key UI Elements
- **NEXT button**: Bottom-right of player controls at approximately (1518, 790). Disabled during playback, enabled after completion.
- **Play/Pause**: Bottom-left at approximately (347, 790)
- **MENU tab**: Left sidebar at approximately (80, 371) — shows course outline
- **TRANSCRIPT tab**: Left sidebar at approximately (145, 371)
- **RESOURCES tab**: Left sidebar at approximately (230, 371)
- **Close button**: Top-right at approximately (1512, 154) — returns to course detail
- **Playback timeline**: Progress bar at approximately (860, 790)

### Troubleshooting
- A "Content not playing properly" modal may appear — dismiss it and try again
- If playback doesn't start, click the Play button in the video area
- If NEXT stays disabled, the video/content hasn't finished yet — wait or check for interactive elements
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

### Workflow to Complete the Course

1. Navigate to the course (search "Secure on the Go" in Viva Learning or use My Learning > In Progress)
2. Click "Open" on the course detail page
3. Wait for loading, then click Play on the start screen
4. For each lesson/section:
   a. Watch/play the video content (wait for it to finish)
   b. If there are interactive elements (quiz questions, clickable items), complete them
   c. When NEXT button enables, click it
   d. Repeat until all sections are complete
5. After completing Section 5, the course should show as completed

### Important Notes
- Do NOT click Close/Back during a lesson — it may lose progress
- The NEXT button position is consistent: bottom-right of the player controls
- Some lessons may have quizzes — look for radio buttons, checkboxes, or "Submit" buttons
- Videos typically last 1-5 minutes per lesson
- The test-out assessment (Section 2) may have multiple-choice questions
