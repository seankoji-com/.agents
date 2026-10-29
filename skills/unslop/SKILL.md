---
name: unslop
description: Cut AI tells from any writing. Must always apply.
---

# Unslop

Edit text to remove AI patterns and add human voice.

## Process

1. Scan for the patterns below.
2. Rewrite. Preserve meaning, match intended tone.
3. Add soul (see next section).
4. Self-audit: "What makes this obviously AI generated?" Fix remaining tells.

## Adding soul

Removing patterns is half the job. Sterile, voiceless writing is just as obvious.

- **Have opinions.** React to facts instead of neutrally listing pros and cons.
- **Vary rhythm.** Short sentences. Then longer ones that take their time. Mix it up.
- **Acknowledge complexity.** "Impressive but also kind of unsettling" beats "impressive."
- **Use "I" when it fits.** First person isn't unprofessional.
- **Let some mess in.** Perfect structure looks machine-made.
- **Be specific.** Not "this is concerning" but "there's something unsettling about agents churning away at 3am."

## Patterns to detect and fix

### Content

1. **Puffery.** "pivotal moment", "testament to", "evolving landscape", "setting the stage for", "indelible mark", "deeply rooted". Cut puffery, state what happened.
2. **Name-dropping.** Listing media outlets without context. Pick one, say what was said.
3. **Superficial -ing phrases.** "highlighting...", "ensuring...", "reflecting...", "showcasing...", "fostering...". Delete or expand with real sources.
4. **Promotional language.** "nestled", "vibrant", "breathtaking", "groundbreaking", "renowned", "stunning", "must-visit". Use neutral descriptions.
5. **Vague attributions.** "Experts believe", "Industry reports suggest", "Some critics argue". Name the source or delete.
6. **Formulaic challenges.** "Despite challenges... continues to thrive." Replace with specific facts.

### Language

7. **AI vocabulary.** Additionally, crucial, delve, enduring, enhance, fostering, garner, interplay, intricate, landscape (abstract), pivotal, showcase, tapestry (abstract), testament, underscore, vibrant. Replace with plain words.
8. **Fancy ways to say "is".** "serves as", "stands as", "boasts", "features". Just say "is" or "has".
9. **"Not just X, but Y."** State the point directly instead.
10. **Rule of three.** Forcing ideas into groups of three. Use the natural number.
11. **Synonym cycling.** Protagonist, main character, central figure, hero all in one paragraph. Pick one, repeat it.
12. **False ranges.** "from X to Y" where X and Y aren't on a meaningful scale. List topics directly.

### Style

13. Avoid em dashes entirely. Use periods or commas.
14. Use colons before lists or examples, not as mid-sentence connectors.
15. Do not bold every proper noun or acronym.
16. Avoid inline-header lists that restate the following sentence.
17. Use sentence case headings.
18. Remove decorative emojis from headings and bullets.
19. Use straight quotes.

### Communication artifacts

20. Remove chatbot phrases such as "I hope this helps!", "Let me know if...", "Of course!", and "Certainly!".
21. Remove cutoff disclaimers. Find sources or omit the claim.
22. Respond directly instead of using a sycophantic tone.

### Filler

23. Replace filler such as "in order to" with "to" and "due to the fact that" with "because".
24. Reduce excessive hedging to the shortest accurate form.
25. Replace generic conclusions with specific plans or facts.

### Jargon

26. Replace abstract metaphor nouns such as "substrate", "vector", "nexus", "bedrock", "scaffolding", "paradigm", "gold-plating", "ratchet", "endgame", "north star", and "flywheel" with the concrete mechanism or action.

### Plain speech

27. Say what something does, not how it feels. If a sentence could appear unchanged in another project's docs, make it specific or cut it.
28. Shorten or split dense sentences. Keep one idea per sentence.
29. Prefer active voice and name the actor when it matters.
30. Cut adverbs or use a stronger verb. Prefer measured changes to words such as "significantly".
31. Prefer plain words: "use" instead of "utilize" or "leverage", and "help" instead of "facilitate".

## Output and boundaries

Return edited prose preserving meaning, citations and requested tone. Keep code,
logs, literal quotations and exact-format content unchanged. Editing a draft
does not authorize sending or publishing it.
