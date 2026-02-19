# RPA Agent Iteration Plan

## Philosophy: 格物致知 (Ge Wu Zhi Zhi)

> "Investigate things to extend knowledge" - Neo-Confucian principle
>
> **Core approach:**
> 1. **Observe deeply** - Watch the agent fail, understand WHY it fails
> 2. **Find root causes** - Don't fix symptoms, fix underlying issues
> 3. **Apply general solutions** - No app-specific hacks, improve the agent's fundamental capabilities
> 4. **Iterate continuously** - Each failure is a learning opportunity

---

## Real-World Task Categories

### Category 1: Web Browser Tasks (Chrome)
1. Search Google and click first result
2. Navigate to a website and fill out a contact form
3. Download a file from a website
4. Open multiple tabs and switch between them
5. Bookmark a page
6. Clear browser history
7. Change browser settings
8. Log into a website (simulated)
9. Copy text from webpage and paste elsewhere
10. Take a screenshot of a specific element

### Category 2: File Management Tasks (pcmanfm/nautilus)
11. Create a new folder
12. Rename a file
13. Move files between folders
14. Delete files (to trash)
15. Copy files
16. Search for files by name
17. Sort files by date/name/size
18. Create a text file with specific content
19. Navigate folder hierarchy
20. Change file permissions

### Category 3: Text Editing Tasks (gedit/vim/nano)
21. Open a file and edit content
22. Find and replace text
23. Save file with new name (Save As)
24. Copy/paste between files
25. Undo/redo operations

### Category 4: Office Tasks (LibreOffice)
26. Create a new document
27. Format text (bold, italic, underline)
28. Create a simple table
29. Save document as PDF
30. Open spreadsheet and modify cells

### Category 5: Multi-Application Workflows
31. Copy text from browser → paste into text editor → save
32. Download file from web → move to specific folder
33. Search for info online → create document with findings
34. Take screenshot → save to folder → rename
35. Open terminal → run command → copy output to file

### Category 6: System Tasks
36. Change desktop wallpaper
37. Adjust screen brightness (simulated)
38. Open system settings
39. Launch application from menu
40. Switch between windows (Alt+Tab)

---

## Measurement Framework

### Metrics to Track
- **Success Rate**: Task completed correctly
- **Steps Taken**: Number of VLM calls to complete task
- **Time to Complete**: Total execution time
- **Error Types**: Categorize failures for pattern analysis
- **Recovery Rate**: Did agent recover from errors?

### Error Categories
1. **Grounding errors**: Wrong coordinates/misidentified elements
2. **Action errors**: Wrong action type selected
3. **Sequence errors**: Correct actions but wrong order
4. **State errors**: Didn't recognize current state
5. **Timeout errors**: Took too long
6. **Stuck loops**: Repeated same action

---

## Iteration Process

### Phase 1: Baseline Testing
- Run each task 3 times
- Record success/failure and error types
- Identify most common failure patterns

### Phase 2: Root Cause Analysis (格物)
- For each failure pattern:
  - What did the VLM see?
  - What did it think?
  - What did it do?
  - What should it have done?
  - WHY did it make the wrong choice?

### Phase 3: General Improvements (致知)
- Based on root causes, implement fixes that:
  - Apply to ALL tasks, not just the failing one
  - Improve fundamental capabilities
  - Don't require app-specific prompts

### Phase 4: Verify & Iterate
- Re-run all tasks
- Confirm improvement without regression
- Document learnings
- Repeat from Phase 1

---

## Improvement Areas (No App-Specific Fixes)

### 1. Visual Understanding
- Better element boundary detection
- Improved text recognition in screenshots
- Understanding of visual hierarchy
- Recognition of interactive vs non-interactive elements

### 2. Action Planning
- Better multi-step reasoning
- State tracking across steps
- Understanding of cause-effect relationships
- Anticipating UI changes after actions

### 3. Error Recovery
- Detecting when action failed
- Trying alternative approaches
- Recognizing stuck states
- Graceful degradation

### 4. Efficiency
- Fewer steps to complete tasks
- Smarter path planning
- Avoiding unnecessary actions
- Parallel operation where possible

---

## Session Log

### Session 4 - 2026-02-16 (Real-World Tasks)

**Start Time**: [timestamp]
**End Time**: [ongoing]

#### Tasks Attempted:
| Task | Result | Steps | Error Type | Notes |
|------|--------|-------|------------|-------|
| ... | ... | ... | ... | ... |

#### Improvements Made:
1. [improvement description]

#### Key Learnings:
1. [learning]

---

## Next Steps

1. Install additional applications in sandbox
2. Start with simple browser tasks
3. Progress to multi-app workflows
4. Document all failures for analysis
5. Implement improvements after each batch

