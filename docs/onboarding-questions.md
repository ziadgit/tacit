# Tacit onboarding: the logic behind the questions

*14 Nov 2026. How Tacit's first conversation with a person is built: what it asks, why, and how it sorts the answers. Apart from the two points marked as agreed, this is a proposal. The source for each design rule is named in the table below and listed in full at the end.*

**Agreed**

- Onboarding is a short phone call the first time a person uses Tacit. They leave a name and number, connect their context, and Tacit calls them.
- A yes or a no can be given by a tap instead of a word. Ideally every answer can be given either way.

## In short

- **A call of about three minutes, three questions.** Each one is about a real thing the person did recently, found in the sources they connected. Each can get one follow-up.
- **No "tell me about yourself".** The agent already has the facts from the connectors. It asks only what the connectors cannot show: what the person noticed, what they rejected, and where their rule stops.
- **A yes is a tap or a word.** The agent phrases every confirmation so that one tap answers it. Everything else is said aloud. Silence is never a yes.
- **The call ends with** a tell-back of each draft skill, two yes-or-no facts about it, and one choice: what the person wants a second opinion on this week.
- **The result:** one to three draft skills confirmed by the person, up to two taste cases, and a first profile. Everything unresolved goes to the calibration period, where the agent asks at the moment a matching real situation comes up.

## Why it looks like this

| What the research found | What onboarding does about it | Source |
|---|---|---|
| An hour of open interview predicted a person's decisions no better than knowing nothing (40.0% against 39.2%). People describe traits, not verdicts | No questions about the person in general. Every question is about one specific past case | Su, Liu & Hu 2026 |
| Five minutes of model-led questions predicted decisions better than people's own written instructions; a written description reaches 95% of its best in five minutes and then stalls | Keep it under five minutes. Longer is not better, sharper is | Li et al. 2023; Wang et al. 2025 |
| People overrate their own rules: confidence in them fell from 5.3 to 3.9 out of 7 after seeing real cases | Never ask "what are your rules for X?". Name a real case and ask what happened | Li et al. 2023 |
| Experts say what they did and leave out what they noticed. Cues come out only when asked; reasons come out best when asking about the option not taken | The follow-up is always about the cue, the rejected option or the what-if | Klein et al. 1989; Hoffman et al. 1998 |
| General questions invite theories; questions about a specific event invite memories. Asking "why" changes the account | No "why" and no "how do you usually". A guess the person only confirmed is kept as a draft until the tell-back | Ericsson & Simon 1980; Nisbett & Wilson 1977 |
| Choosing between concrete options works: model-written yes-or-no questions and cases to label predicted people's decisions better than the instructions they wrote themselves | When a person hesitates, the agent offers one concrete guess that a tap can confirm | Li et al. 2023; Wang et al. 2025 |
| A witness who cannot describe a face can still assemble it from a picture kit. In the design studio the words mean nothing without the drawing | Name the person's own thing, or two of their things, instead of asking them to describe from scratch. The things stay attached to what is stored | Polanyi 1966; Schön 1983 |
| Describing a whole-impression judgement can interfere with it, for people who see more than they have words for | For taste: the verdict first. If the words do not come, keep the verdict and the example, and do not press | Schooler & Engstler-Schooler 1990; Melcher & Schooler 1996 |
| Gains flatten after about four demonstrations; one example cannot convey a standard | Three anchors at onboarding are enough to start; more cases per standard are collected later | Shaikh et al. 2024; Sadler 1989 |
| Recent and unusual cases are reported most accurately; routine ones least | Anchors come from the last two weeks and from things that did not go the routine way | Clark et al. 2008 |
| Intuition is trustworthy only with many repetitions and fast, clear feedback, and it is per task, not per person. Confidence is not a signal | Two facts per skill: how many times, how fast the feedback. No confidence rating | Kahneman & Klein 2009 |
| Telling the story back and letting the expert correct it is a step of the interview method itself | Every draft skill is told back before it is kept | Hoffman et al. 1998 |

## The call

| Step | What the agent says | By voice | By tap | Time |
|---|---|---|---|---|
| Before the call | Nothing. The person has left a name and number and connected their sources. The agent reads them and picks three anchors | | | |
| Opening | Who is calling, how long it takes (three questions, three minutes), and how to answer: "say it, or tap for yes" | "OK" | Tap | ~15 s |
| 1. A correction | Names a real moment when the person corrected something (an agent, a draft, a colleague) and asks what happened the first time. The best source of rules | Tells what happened | | ~1 min |
| 2. A pair | Names two of their own things with opposite outcomes, one accepted and one sent back, and asks what separated them. The best source of taste | Says what separated them | | ~1 min |
| 3. A hard recent case | Names a real, non-routine moment with an ending and asks what they were seeing or hearing. The best source of cues | Says what they noticed | | ~1 min |
| Follow-up, when needed | One question about the cue, the rejected option or the limit. If the person hesitates, one concrete guess: "Was it that …? Tap for yes, or tell me what it was" | Says it their own way | Tap confirms the guess | inside each minute |
| 4. Tell-back | Each draft skill in one sentence: "Did I get that right?" | "Yes", or says the fix | Tap for yes | ~30 s |
| 5. Two facts per skill | "Have you done this dozens of times or more?" and "Do you usually find out within a week whether it worked?" | "Yes" or "no" | Tap for yes | ~15 s |
| 6. One choice | Names three things coming up this week and asks which they would like a second opinion on | Says which | Tap when the agent names the one they want | ~15 s |
| Close | What was kept, what is still a draft, and that nothing is shared until they say so | | | ~10 s |

If a connector gives no usable anchor, the question is taken from the fallback set near the end.

**What a tap is worth, and what a spoken answer is worth**

- A tap means yes to the thing just said: a draft skill, a fact, a guess. For a verdict that is good evidence.
- A tap on the agent's guess confirms the agent's wording, not the person's. It is stored as "confirmed a suggestion" and stays a draft until the tell-back.
- A spoken answer is the person's own words. Only those are quoted in a skill, and only those can carry something the agent did not think to suggest.
- Silence is never a yes. With neither a tap nor a word, the agent asks once more, then moves on and leaves the item as a draft.

## Before the call: from connected sources to anchors

An **anchor** is one real thing the person did, which a question will be about. For each connected source the agent looks for the signals below.

| Source | What the agent looks for | Anchor type |
|---|---|---|
| The person's agents (Claude Code, Codex): instruction files, memory notes, skill files, corrections in sessions | A rule the person told the agent more than once; a correction ("not like that, like this"); the skill they run most; an output they accepted and one they rewrote | Correction; pair; repeated pattern |
| Vexo band: conversation transcripts | The person saying "always", "never", "the trick is", "what I do is"; the person answering someone's "why did you do that?"; a story with an ending | Hard recent case; correction |
| Calendar | Invites declined against invites accepted; a meeting they moved or cut short; recurring one-on-ones; a hard meeting coming up | Pair; hard recent case; what is coming up |
| Email | A reply where they pushed back, declined or rewrote the plan; a long reply after a short question; a draft sent after several rewrites | Correction; hard recent case |
| Code review (GitHub) | A review where they asked for changes; one they approved in minutes against one they sent back | Pair; correction |
| Team chat (Slack) | A message where they corrected someone or explained a decision when asked | Correction |
| Documents (Notion, Google Docs) | Their edits to someone else's draft; a section they cut; their comments | Correction; pair |
| Sales records (HubSpot and similar) | A deal they marked lost or moved back a stage; a note after a call | Hard recent case |
| Design files (Figma) | A version they picked over another; a comment asking for a change | Pair |
| A public link (LinkedIn, blog) | A post where they describe how they do something | Repeated pattern, to be checked against a real case |

**Sources with no history yet.** At first use some sources are empty. A band that has just been paired has nothing recorded, so its anchors come later, in calibration. A band with earlier recordings, the person's agents, the calendar and email have history from the first minute, so onboarding leans on those.

**Scoring an anchor.** One point for each: it happened in the last two weeks; something did not go the routine way (rejected, rewritten, declined, corrected); it has an ending; it is the person's own action or words; it can be named without exposing anyone else. Keep anchors with four or five points.

**Working areas.** The agent guesses the person's areas from the sources and anchors, not from a job title: code (code review, agent skills about code), selling (sales records, outbound email), managing people (recurring one-on-ones, meetings they run), writing (document edits), design (design files), founder mix (several of these). It takes the top two.

**Picking the three.** One correction, one pair, one hard recent case, spread over the top two areas, preferring the highest scores. If the person's agents are connected, the correction comes from there: a rule someone bothered to tell their agent twice is the strongest signal there is.

## The questions

Each template is filled with the person's own anchor. Other people are never named: "a colleague", "an investor", "the author of the draft".

| Anchor type | Opening question | What it yields |
|---|---|---|
| Correction | "On Tuesday you told your agent: «…». What happened the first time that made you add that?" | The rule, its trigger, and the story behind it |
| Correction (a draft or a person) | "You cut a section from the draft you reviewed on Monday. What was wrong with it?" | A rule or a taste verdict, tied to the thing |
| Pair | "Last week you approved one change in four minutes and sent another one back. What separated them?" | A verdict and the contrast that decided it |
| Pair (calendar) | "Last week you declined three invites and accepted eleven. What did the three have in common?" | A rule for saying no |
| Hard recent case | "On Thursday's call you changed the plan halfway through. What were you seeing or hearing at that point?" | The cue and the action |
| Repeated pattern | "You do «…» before every «…». Was there a time recently when you didn't? What was different?" | Where the rule stops |

**For a pair, the verdict is already there.** The person accepted one thing and sent the other back; the agent only asks what separated them. If no words come, the pair is stored as a verdict with links to the two things, and the agent does not press.

**The one follow-up.** It depends on what the answer is missing (see the next section). The four that work:

1. "What were you seeing or hearing at that point?" (the cue)
2. "What else could you have done, and why not that?" (the rejected option)
3. "What would have had to be different for you not to do it?" (the limit)
4. "What would someone newer have got wrong there?" (the contrast with a beginner)

Never: "why did you decide that?" or "how do you usually handle this?".

## Classifying the answer

The agent sorts each answer into one class and takes one action. One follow-up at most; after that the answer is kept as it is or dropped.

| The answer looks like | Illustration | Class | What the agent does |
|---|---|---|---|
| A trigger, an action, enough detail, a result | "When a cold email runs past five sentences I cut it to five with one ask, and replies went up." | Skill, complete | Drafts the skill and tells it back |
| An action with no situation | "I just cut it down." | Skill missing its cue | Follow-up 1 |
| A situation with no how | "When a deal stalls I re-engage." | Skill missing detail | "What exactly did you say or do?" |
| A rule with no limit | "I always ask for the budget first." | Skill missing its limit | Follow-up 3 |
| A verdict that points at something | "The first one. It did one thing; the second did three." | Taste case | Stores the pair and the reason, linked to the two things. No more questions now; a second pair for the same standard is queued for calibration |
| A verdict with no words | "The first one just felt right." | Taste case, verdict only | Stores the verdict and the links. Does not ask for the reason. Queues a second pair |
| A story with no action | "We nearly ran out of money twice. It was wild." | Story | "What did you do at the turning point?" If still no action, drops it |
| A belief | "Remote teams never ship anything great." | Opinion | Not stored. One redirect: "When did you last see that happen? What did you do?" |
| A description of themselves | "I'm very detail-oriented." | Trait | Not stored as a skill. One redirect: "When did that last matter? What happened?" |
| Something that depends on one relationship | "I just ring my old boss on their board." | Not transferable | Kept as a private note, not a skill |
| Someone else's words or method | "My co-founder says you should…" | Not theirs | Dropped: only the speaker's own practice |

These classes are the five checks in practice: action, situation, enough detail, result, transferable. A complete skill passes all five. Each "missing" class names the check that failed and the follow-up that repairs it.

**Rules that always hold**

- Verdict first, words second.
- A yes can always be a tap. What the person confirmed by tap and what they said in their own words are stored apart.
- One follow-up per answer, and it stays inside the case just told.
- Stop after three anchors or four minutes, whichever comes first.
- A skill is stored with four parts where they exist: what the person noticed, what they expected, what they were after, what they did. Plus "when it does not apply".
- The reason is stored as "the author's stated reason". A reason that departs from the usual practice of the trade is marked untested.
- Nothing is shared without the tell-back and the person's yes.

## Two facts and one choice

**Per skill, two yes-or-no questions.**

| Question | Yes | No |
|---|---|---|
| "Have you done this dozens of times or more?" | practised | done a few times |
| "Do you usually find out within a week whether it worked?" | fast feedback | slow feedback, or none |

The skill shows both answers in plain words, for example "done many times; finds out within a week if it was wrong". Two yeses is the kind of judgement the research says can be trusted. Two noes is an opinion with a name on it, and the profile should say so plainly. No confidence rating is asked or shown.

**One choice, for the learning side.** The agent names three things from what is coming up in the person's sources, for example a pitch on Thursday, a large code review and a hard email waiting for a reply, and asks which they would like a second opinion on this week. The answer decides whose skills are suggested first. This replaces "what do you want to learn?", which would be another question about the person in general.

## What onboarding produces

| Part of the profile | Where it comes from |
|---|---|
| Working areas (top two) | The connected sources and anchors, with no question asked |
| One to three confirmed skills | Questions 1 and 3, after the tell-back |
| Up to two taste cases | Question 2 |
| A trust line on each skill | The two facts |
| "Wants a second opinion on…" | The one choice |
| Open items for calibration | Answers that stayed incomplete; second pairs for each taste standard; rules found in the sources that were not asked about |

Each line of the profile keeps its source: from the connected sources, said on the call, confirmed by tap, or heard later.

## If nothing is connected

Four fallback questions, still about specific cases. The agent picks three.

1. "Think of something in the last two weeks that went better than expected because of something you did. What did you do?"
2. "What is one thing you corrected in someone else's work this week? What was wrong with it?"
3. "Think of the last time you said no to something most people would have said yes to. What told you to say no?"
4. "Think of two pieces of work from this month, one you were happy to send and one you held back. What separated them?"

## What not to ask

| Question | Why not |
|---|---|
| "Tell me about yourself", "What are your strengths?" | Self-description does not predict what a person decides |
| "What are your rules for hiring?" | A general question gets a theory, and people overrate their own rules |
| "Why did you decide that?" | It asks for a cause the person may not have access to, and it changes the account. Ask what they noticed or what they rejected |
| "So you always do X, right?", with no case named | A leading question about a rule in general is weak evidence. A yes-or-no about a concrete case, a draft skill or consent is fine, by tap or by voice |
| "Describe your taste in design." | Words for a whole impression can get in the way. Ask about two real things |
| Ten more questions | Quality stops improving after about five minutes |

## A worked example (illustration)

A founder has left a number and connected three sources: their coding agent, a calendar, and a Vexo band with earlier recordings. Tacit calls.

> **Tacit:** Hi, this is Tacit. Three questions, about three minutes. Say your answers, or tap for yes. Ready?
> *(tap)*
> **Tacit:** You told your coding agent twice: "split the change before asking for review". What happened the first time that made you add that?
> **Founder:** A review sat for three days because nobody wanted to open it. I split it in two and both were approved the same afternoon.
> **Tacit:** What were you seeing in that first review that told you it was too big?
> **Founder:** It moved code around and changed what the code does in the same change. You can't tell which lines matter.
> **Tacit:** Last week you declined three invites and accepted eleven. What did the three have in common?
> **Founder:** None of them said what we had to decide.
> **Tacit:** What would have had to be different for you to go anyway?
> **Founder:** If it was a customer.
> **Tacit:** On Thursday's customer call you dropped the demo halfway. What were you hearing at that point?
> **Founder:** They kept coming back to what the problem costs them, not to the product.
> **Tacit:** Here is the first one. "Before asking for review, check the change does one thing; if it both moves code and changes behaviour, split it." Did I get that right?
> *(tap)*
> **Tacit:** Have you done this dozens of times or more?
> *(tap)*
> **Tacit:** Do you usually find out within a week whether it worked?
> *(tap)*

The same follows for the other two. One is corrected by voice and kept as a draft. The founder then picks Thursday's pitch as the thing they want a second opinion on.

## How this maps onto SPEC.md

These are proposals for the build spec, not changes to it. `SPEC.md` is untouched.

**§6, the context.** Today the interviewer gets the kept items from the Exa lookup: `role`, `expertise`, `work`, `writing`, `other`. Those are enough to tailor the first question:

| What was kept | Opening question |
|---|---|
| A `writing` item where they describe how they do something | "You wrote that you «…». When did you last do that, and what happened?" |
| A `work` item: a project, a launch, a talk | "You «…». Think of one moment in it that did not go the routine way. What did you do?" |
| Only a `role` or `expertise` item | "Think of the last time something in «expertise» went better than expected because of something you did. What did you do?" |
| Nothing kept | The fallback questions above |

The richer anchors in this document (corrections to the person's own agents, declined invites, code reviews, band recordings) need those sources to be connected. They fit the same `context` variable: one line per anchor instead of one line per fact.

**§7, the interviewer prompt.** The current prompt asks "why they do it their way". The research says to ask what they noticed and what they rejected instead, and to keep every question inside one concrete case. A full replacement for `SYSTEM_PROMPT`, same length and same tool:

> You are tacit's interviewer. You are talking with {{name}}. What they confirmed about themselves: {{context}}. Your job is to draw out one to three skills: things they know how to do that they never wrote down. Start from something specific in what they confirmed: name it and ask about the last time they did it. Always ask about one concrete recent situation, never about how they usually work. First let them tell what happened and what they did. Then ask one follow-up about whatever is missing: what they were seeing or hearing that told them to do it; what else they could have done and why not that; what would have had to be different for them not to do it; or what someone newer would have got wrong there. Do not ask "why". If they answer with an opinion or a description of themselves, ask once when that last happened and what they did. Ask one short question at a time and let them talk. When you have heard a skill clearly, call note_skill with a short imperative title, the verdict (when to do it and what to do), the reason (as they gave it), and their own exact words as the quote. Then say in one sentence what you saved and ask if it's right; they can say yes or tap yes in the app. Never invent anything they didn't say. Never ask about their private life, health, money or other people's details. After three skills, or when they want to stop, thank them and say their skills are waiting for them in the app. Short sentences. No lists.

**§7, the tap.** The app already polls the call status every three seconds while a call is active. A "yes" button on that screen during the tell-back would give the tap; a spoken yes keeps working.

**§3 and §8, the skill and the check.** In the spec's terms: the verdict carries the cue and the action ("when …, do …"), the reason is the author's stated reason, the quote is their own words. The two Jev questions, `specific` and `own`, already cover the five checks closely enough; nothing to change there.

**Length.** `interview_max_seconds` is 600. The questions above aim at three to four minutes, which leaves room for a person who wants to keep talking.

## Open questions

1. Which tap: a button in the app while the call is running, the band's double-tap, or a key on the phone? Is the band already on the wrist during the first call?
2. Which sources can be connected before the call on day one? The build spec has the public lookup and the person's own links; the profile prototype also shows the person's agents, the Vexo band and a calendar.
3. May the agent read the person's corrections to their own agents right after sign-up, or only after a separate yes for that source?
4. Does a yes on the call keep a skill private only, or can it also publish it? The proposal above keeps everything private until a separate yes.
5. If a person only confirmed the agent's guess by tap, is that enough to keep the skill, or must they say it in their own words first? The proposal above accepts a confirmed tap.

## Sources

How much of each was read: ✅ full text · ◐ part of the text.

- Clark, R. E., Feldon, D. F., van Merriënboer, J. J. G., Yates, K. A., & Early, S. (2008). Cognitive task analysis. Handbook chapter. ◐
- Ericsson, K. A., & Simon, H. A. (1980). Verbal reports as data. *Psychological Review, 87*(3), 215–251. [doi:10.1037/0033-295X.87.3.215](https://doi.org/10.1037/0033-295X.87.3.215) ◐
- Hoffman, R. R., Crandall, B., & Shadbolt, N. (1998). Use of the Critical Decision Method to elicit expert knowledge: A case study in the methodology of cognitive task analysis. *Human Factors, 40*(2). ✅
- Kahneman, D., & Klein, G. (2009). Conditions for intuitive expertise: A failure to disagree. *American Psychologist, 64*(6), 515–526. [doi:10.1037/a0016755](https://doi.org/10.1037/a0016755) ✅
- Klein, G. A., Calderwood, R., & MacGregor, D. (1989). Critical decision method for eliciting knowledge. *IEEE Transactions on Systems, Man, and Cybernetics, 19*(3), 462–472. [IEEE](https://ieeexplore.ieee.org/document/31053) ✅
- Li, B. Z., Tamkin, A., Goodman, N., & Andreas, J. (2023). Eliciting human preferences with language models. [arXiv:2310.11589](https://arxiv.org/abs/2310.11589) ✅
- Melcher, J. M., & Schooler, J. W. (1996). The misremembrance of wines past: Verbal and perceptual expertise differentially mediate verbal overshadowing of taste memory. *Journal of Memory and Language, 35*, 231–245. [Author copy](https://metalab.psych.ucsb.edu/sites/default/files/publications/1996/1996-The-misremembrance-of-wines-past-Verbal-and-perceptual-expertise-differentially-mediate-verbal-overs.pdf) ✅
- Nisbett, R. E., & Wilson, T. D. (1977). Telling more than we can know: Verbal reports on mental processes. *Psychological Review, 84*(3), 231–259. [University of Michigan copy](https://deepblue.lib.umich.edu/bitstream/2027.42/92167/1/TellingMoreThanWeCanKnow.pdf) ✅
- Polanyi, M. (1966). *The Tacit Dimension*, chapter 1. [University of Chicago Press](https://press.uchicago.edu/ucp/books/book/chicago/T/bo6035368.html) ✅
- Sadler, D. R. (1989). Formative assessment and the design of instructional systems. *Instructional Science, 18*, 119–144. [doi:10.1007/BF00117714](https://link.springer.com/article/10.1007/BF00117714) ✅
- Schön, D. A. (1983). *The Reflective Practitioner*, chapter 3. ✅
- Schooler, J. W., & Engstler-Schooler, T. Y. (1990). Verbal overshadowing of visual memories: Some things are better left unsaid. *Cognitive Psychology, 22*, 36–71. [Author copy](https://metalab.psych.ucsb.edu/sites/default/files/publications/1990/1990-Verbal-overshadowing-of-visual-memories-Some-things-are-better-left-unsaid.pdf) ✅
- Shaikh, O., Lam, M., Hejna, J., Shao, Y., Bernstein, M., & Yang, D. (2024). Show, don't tell: Aligning language models with demonstrated feedback. [arXiv:2406.00888](https://arxiv.org/abs/2406.00888) ✅
- Su, R., Liu, Y., & Hu, J. (2026). What a one-hour interview does not tell an LLM about you: Interviews elicit traits, not decision policies. [arXiv:2605.29458](https://arxiv.org/abs/2605.29458) ✅
- Wang et al. (2025). A CHI 2025 study in which 37 people built a personal content filter by labelling examples, writing rules and writing a prompt. [arXiv:2409.03247](https://arxiv.org/abs/2409.03247) ✅
