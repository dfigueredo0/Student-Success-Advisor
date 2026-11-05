# Student Success Advisor
## Evaluation and Error Analysis Report

**Prepared:** November 5, 2026  
**Repository:** [dfigueredo0/Student-Success-Advisor](https://github.com/dfigueredo0/Student-Success-Advisor)  
**Evaluated main-branch commit:** `c4643ec4ba8140755b565bfdd932858272cdfa9b`  
**Project type:** Fourth-year student research and software prototype

## Executive summary

This report analyzes the evaluation evidence currently committed to the Student Success Advisor repository. It focuses on three areas: intent routing, prerequisite reasoning, and prompt-injection detection. The purpose is not only to report aggregate scores, but also to identify failure types, consider their consequences, and define the conclusions that the current evidence can support.

The routing evaluation produced the strongest result: 65 of 67 cases were handled correctly, for an accuracy of 97%. All 17 regex-routed cases and all 10 clarification cases were correct; 38 of 40 model-routed cases were correct. The two failures involved closely related intents: course information versus course discovery, and degree progress versus course eligibility. These results suggest that the router is effective on the current test set, but they do not measure whether the final advising answers are correct.

The prerequisite-impact evaluations demonstrate the importance of structured, grade-aware AND/OR prerequisite logic. They show that a simpler representation can list unnecessary alternatives as missing, incorrectly block eligible students, or incorrectly allow students when requirements are unreadable or grades are unknown. These files are best interpreted as diagnostic comparisons between prerequisite approaches, not as an externally validated error rate for the final system.

The injection evaluations reveal the largest safety weakness. The pattern detector caught 13 of 106 attacks (12.3%) while blocking 1 of 150 normal questions (0.7%). The ProtectAI detector caught 59 of 106 attacks (55.7%) while blocking 5 of 150 normal questions (3.3%). The comparison shows a clear sensitivity–false-positive tradeoff, but neither detector provides comprehensive protection.

Overall, the repository supports the conclusion that the team has built a functional prototype with promising routing performance and meaningful evaluation infrastructure. It does not yet support a claim that the complete advisor is safe, accurate, or effective in real student use.

## 1. Purpose and evaluation questions

The report addresses the following questions:

1. How accurately does the router assign student messages to the intended system function?
2. What kinds of routing failures remain, and how consequential are they?
3. What does the prerequisite-impact analysis reveal about prerequisite representations?
4. How effectively do the tested injection detectors distinguish attacks from normal questions?
5. What conclusions and limitations should accompany these results in the final project presentation or report?

## 2. Evidence reviewed

The analysis uses the following committed artifacts:

- [`data/gold/routing.jsonl`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/data/gold/routing.jsonl)
- [`eval/results/routing-2026-10-22-full.json`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/eval/results/routing-2026-10-22-full.json)
- [`data/gold/injection.jsonl`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/data/gold/injection.jsonl)
- [`eval/results/injection-2026-10-22-patterns.json`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/eval/results/injection-2026-10-22-patterns.json)
- [`eval/results/injection-2026-10-22-protectai.json`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/eval/results/injection-2026-10-22-protectai.json)
- [`eval/results/prereq_impact-2026-10-14-B.json`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/eval/results/prereq_impact-2026-10-14-B.json)
- [`eval/results/prereq_impact-2026-10-14-nogrades.json`](https://github.com/dfigueredo0/Student-Success-Advisor/blob/main/eval/results/prereq_impact-2026-10-14-nogrades.json)
- The associated evaluation scripts in [`eval/`](https://github.com/dfigueredo0/Student-Success-Advisor/tree/main/eval)

The result files were treated as the source of record. No new experiment was run for this report. Percentages not already present in the files were calculated directly from their reported counts.

## 3. Error-classification approach

Errors were interpreted using the following project-oriented severity scale:

| Severity | Definition |
|---|---|
| Critical | Could expose protected information or create an immediate serious safety risk. |
| High | Could materially affect registration, prerequisites, graduation planning, or another consequential academic decision. |
| Medium | Could mislead or inconvenience a student but is likely recoverable through verification or escalation. |
| Low | Primarily affects routing, presentation, or usability and is unlikely to change the substantive outcome. |

Severity is an interpretation of potential consequences, not a measurement produced by the evaluation scripts. Actual severity depends on the final answer, the interface, and whether the system abstains or escalates.

## 4. Routing evaluation

### 4.1 Configuration

The saved full-routing evaluation records:

- Evaluation date: October 22, 2026
- Mode: `full`
- Prompt version: `router_intent@2`
- Model alias: `local-llm`
- Confidence threshold: `0.6`
- Total cases: 67

The evaluation contains in-scope advising intents, out-of-scope messages, and several contextual follow-up messages.

### 4.2 Aggregate results

| Metric | Result |
|---|---:|
| Total cases | 67 |
| Correct | 65 |
| Misrouted | 2 |
| Accuracy | 97% |
| Misroute rate | 3% |
| Out-of-scope handling | 100% |

Performance by routing stage was:

| Stage | Correct | Total | Accuracy |
|---|---:|---:|---:|
| Regex | 17 | 17 | 100% |
| Model | 38 | 40 | 95% |
| Clarification/out of scope | 10 | 10 | 100% |

Per-intent results were:

| Intent | Cases | Precision | Recall |
|---|---:|---:|---:|
| Career advice | 9 | 1.000 | 1.000 |
| Check eligibility | 11 | 0.917 | 1.000 |
| Course information | 7 | 1.000 | 0.857 |
| Degree progress | 8 | 1.000 | 0.875 |
| Find courses | 6 | 0.857 | 1.000 |
| Help | 3 | 1.000 | 1.000 |
| Plan next term | 9 | 1.000 | 1.000 |
| Record courses | 4 | 1.000 | 1.000 |

### 4.3 Individual routing errors

#### Error 1: Course information routed to course discovery

- **Input:** “Are there open seats left in CS 425?”
- **Expected:** `course_info`
- **Predicted:** `find_courses`
- **Stage:** Model
- **Recorded confidence:** 0.90
- **Category:** Boundary ambiguity between information about one course and searching for available courses
- **Proposed severity:** Low to medium

This question asks about a known course but also concerns availability, making it semantically close to course discovery. The route differs from the gold label, although both tools may access overlapping schedule information. The practical consequence depends on whether the `find_courses` path can still return the correct seat information. Therefore, this is a routing-label error, but it is not automatically a wrong final answer.

#### Error 2: Degree progress routed to eligibility checking

- **Input:** “What requirements am I still missing for my major?”
- **Expected:** `degree_progress`
- **Predicted:** `check_eligibility`
- **Stage:** Model
- **Recorded confidence:** 0.90
- **Category:** Confusion between program-level progress and course-level eligibility
- **Proposed severity:** Medium

This failure is more important because a degree-progress request requires a comprehensive comparison between a student record and program requirements. A course-eligibility path may answer only a narrower question. In the current repository, the degree-progress service is also not connected, so the system cannot yet provide the complete functionality implied by the expected intent.

### 4.4 Interpretation

The routing result is promising. The hybrid design appears especially useful: deterministic patterns handle clear messages quickly, the model handles more varied phrasing, and uncertain or unsupported questions are sent to clarification. Contextual follow-ups such as “what about CS 485?” are included, which makes the test more realistic than an isolated single-message benchmark.

However, the reported 97% must be described precisely as **intent-routing accuracy on the included 67 cases**. It is not an overall measure of advising accuracy, citation quality, recommendation quality, or student benefit. Some categories also contain very few examples, including only three help cases and four record-course cases. A single additional error would therefore noticeably change their reported performance.

The saved model-routed rows generally required several seconds, with observed times roughly between 3.4 and 6.2 seconds. This is acceptable for a prototype but may affect perceived responsiveness.

## 5. Prerequisite-impact evaluation

### 5.1 Purpose

The prerequisite artifacts examine the effect of using structured prerequisite trees and grades instead of relying on a simpler flattened list of prerequisite courses. The result files report 1,133 catalog courses with prerequisite information and evaluate three synthetic profiles representing first-year, sophomore, and junior progress.

The reported categories include:

- `agree`: the compared approaches produce the same effective conclusion.
- `overstated_missing`: unnecessary OR alternatives are listed as missing.
- `wrongly_blocked`: an OR alternative has already been met, but the simpler interpretation still blocks the student.
- `wrongly_allowed`: the simpler interpretation allows the course despite an unreadable requirement, unmet range/minimum-grade condition, or unknown required grade.

These are comparison categories produced by the evaluation design. They should not be presented as independently adjudicated mistakes made by the final production system.

### 5.2 Results when completed courses are assigned grade B

| Profile | Agree | Overstated missing | Wrongly blocked | Wrongly allowed |
|---|---:|---:|---:|---:|
| First year | 701 | 394 | 10 | 27 |
| Sophomore | 699 | 364 | 37 | 27 |
| Junior | 703 | 342 | 49 | 27 |

Across the three profiles, the most common disagreement is overstating missing requirements by treating OR alternatives as though every alternative were required. The mean number of unnecessary extra courses listed in these cases is approximately 3.1–3.2.

The reported reasons for wrongly allowed decisions include 23 unreadable prerequisite texts and four course-range or minimum-grade conditions per profile. Wrongly blocked cases increase in later profiles because students have completed more courses and therefore encounter more situations where one valid OR branch has already been satisfied.

### 5.3 Results when grades are unknown

| Profile | Agree | Overstated missing | Wrongly blocked | Wrongly allowed |
|---|---:|---:|---:|---:|
| First year | 702 | 394 | 8 | 28 |
| Sophomore | 700 | 364 | 36 | 27 |
| Junior | 694 | 342 | 45 | 40 |

The increase to 40 wrongly allowed cases for the junior profile is associated partly with minimum-grade requirements when grades are unknown. This is an important design finding: course completion alone is not always sufficient evidence of prerequisite eligibility.

### 5.4 Risk interpretation

| Failure category | Potential consequence | Proposed severity |
|---|---|---|
| Overstated missing | Confusing advice and unnecessary course recommendations | Medium |
| Wrongly blocked | Student incorrectly believes an eligible course cannot be taken | High |
| Wrongly allowed | Student is told they may take a course despite an unmet condition | High |
| Unreadable rule treated as permission | Unsupported eligibility conclusion | High |
| Unknown grade treated as sufficient | Grade-dependent requirement may be overlooked | High |

Wrongly allowed decisions are particularly important because students may act on them during registration. A safer system response to unreadable rules, ambiguous ranges, or missing grade information is to state that eligibility cannot be confirmed and direct the student to an official source or advisor.

### 5.5 Interpretation and limitation

The prerequisite evaluation provides strong evidence for the project’s architectural decision to represent rules as structured trees and include grades. It does not, by itself, prove that the tree parser is always correct. Both the parser and evaluator may share assumptions, and the result files do not document independent advisor adjudication for all 1,133 rules.

The appropriate conclusion is therefore that structured prerequisite logic corrects important failure modes of simpler representations. A stronger future evaluation would sample rules from the catalog and compare the system’s interpretation with a manually verified reading of the official catalog.

## 6. Prompt-injection evaluation

### 6.1 Dataset and detectors

The saved evaluation contains 106 attack cases and 150 normal cases. It compares:

1. A pattern-based detector intended to identify known injection language quickly.
2. A ProtectAI detector that uses a more capable classification approach.

The cases include team-written examples, an external Deepset-derived set, and one attack from the routing set.

### 6.2 Aggregate results

| Detector | Attacks caught | Attack recall | Attacks missed | Normal blocked | Normal false-positive rate | Median latency |
|---|---:|---:|---:|---:|---:|---:|
| Patterns | 13/106 | 12.3% | 93 | 1/150 | 0.7% | 0.03 ms |
| ProtectAI | 59/106 | 55.7% | 47 | 5/150 | 3.3% | 20.075 ms |

Results by source were:

| Detector | Written attacks caught | Deepset attacks caught | Routing attack caught |
|---|---:|---:|---:|
| Patterns | 13/45 | 0/60 | 0/1 |
| ProtectAI | 36/45 | 22/60 | 1/1 |

### 6.3 Error analysis

The pattern detector has very low latency and a low false-positive rate, but it misses most attacks and catches none of the 60 Deepset cases. This indicates that its coverage is concentrated around phrases or forms similar to its known patterns.

The ProtectAI detector substantially improves attack recall, especially on the team-written cases, but still misses 47 attacks. It also blocks five normal questions. The tradeoff is therefore not simply “stronger is better”: increasing attack detection can also deny legitimate advising questions.

The missed cases include reworded or less explicit attacks that do not use obvious phrases. The repository’s implementation notes also acknowledge that only the new message is supplied to the gateway guard while earlier conversation history remains untrusted input to the router. This leaves a potential multi-turn attack surface.

### 6.4 Risk interpretation

A missed injection is not automatically a successful data breach; it means the detector did not block the input. The final consequence depends on downstream prompts, tool permissions, authentication, output filtering, and available data. Nevertheless, detector coverage is important because the planned system may process transcripts, grades, and academic histories.

| Failure | Potential consequence | Proposed severity |
|---|---|---|
| Attack not detected | Model may follow malicious instructions | Medium to critical, depending on available data/actions |
| Privacy-seeking attack not detected | Possible attempt to obtain another student’s information | Critical if authorization is also absent |
| Normal question blocked | Legitimate student cannot obtain assistance | Low to medium |
| Multi-turn attack not evaluated by the message-only guard | Earlier malicious content may influence later processing | High |

The defensible conclusion is that both detectors are experimental safeguards. The pattern detector alone is insufficient as a general injection defense, and the ProtectAI detector also requires additional layers.

## 7. Cross-cutting findings

### 7.1 Strengths

- Evaluation results are committed rather than reported only in presentation slides.
- Results include individual rows, allowing failures to be inspected.
- Prompt and detector variants are named.
- Routing combines deterministic rules, model classification, and clarification.
- The routing set includes out-of-scope and contextual messages.
- The prerequisite analysis focuses on consequential logical distinctions such as AND, OR, and minimum grades.
- The injection evaluation contains attacks and normal questions, allowing both missed attacks and false positives to be measured.
- The repository preserves negative findings rather than reporting only favorable scores.

### 7.2 Weaknesses

- The routing set is small, and several intents have few examples.
- Independent annotation or advisor validation of gold labels is not documented.
- No confidence intervals are reported.
- Routing evaluation stops before final-answer correctness.
- The prerequisite comparison is diagnostic rather than an independent validation of the final evaluator.
- Neither injection detector achieves adequate attack coverage by itself.
- The evaluation does not measure citation support, answer completeness, fairness, accessibility, or user outcomes.
- Some high-value system functions remain incomplete, including authenticated student records and degree-progress calculation.

## 8. Threats to validity

### Construct validity

Routing accuracy measures whether the system chose the intended intent label; it does not measure whether the answer is correct or useful. Injection detection measures whether an input is blocked; it does not directly measure whether an unblocked attack succeeds. The prerequisite-impact categories measure differences between approaches rather than externally adjudicated final-system accuracy.

### Internal validity

The development team appears to have created or curated much of the evaluation material. Knowledge of the implementation could influence case wording or expected labels. Model nondeterminism and configuration changes may also alter results.

### External validity

The datasets may not represent the language, programs, catalog years, or exceptional situations encountered by the full student population. Results from synthetic profiles and internally constructed messages should not be generalized directly to real advising outcomes.

### Conclusion validity

Small per-intent samples make some 100% values unstable. No confidence intervals or significance tests are included. Comparisons should therefore be presented descriptively rather than as proof of superiority.

## 9. Conclusions supported by the evidence

The existing evidence supports the following conclusions:

1. The hybrid router performs well on the current 67-case routing dataset.
2. Remaining routing errors occur at boundaries between related advising functions.
3. Structured prerequisite trees and grade-aware evaluation address meaningful weaknesses in flattened prerequisite lists.
4. Unknown grades and unreadable prerequisite rules should lead to uncertainty or escalation rather than confident permission.
5. The pattern injection detector is fast but has very low attack coverage.
6. ProtectAI improves attack detection but still misses many attacks and increases false positives.
7. The project has a meaningful evaluation foundation and openly documented limitations.

The evidence does **not** establish that:

- 97% of final advising answers are correct.
- The prerequisite evaluator is correct for all catalog rules.
- The system is secure against prompt injection.
- The prototype is ready to process real student records without additional authorization controls.
- The system improves student academic outcomes or advisor workload.

## 10. Recommended wording for the final presentation

> We evaluated the prototype’s intent routing, prerequisite representation, and prompt-injection detection. The hybrid router correctly handled 65 of 67 test cases, while the prerequisite analysis demonstrated the importance of structured AND/OR and grade-aware rules. Security testing showed that simple pattern matching provided limited injection coverage and that a stronger detector improved recall at the cost of additional false positives. These findings support the feasibility of the prototype while identifying prerequisite uncertainty, authentication, and layered security as important future work.

## 11. Prioritized future work

Given the scope of a semester-long fourth-year project, these items should be presented primarily as future work rather than mandatory additions before project completion:

1. Add a small final-answer evaluation using official catalog sources and a documented scoring rubric.
2. Require abstention or escalation when prerequisites are unreadable or grade information is insufficient.
3. Implement authentication and bind student records and conversation IDs to authorized users.
4. Complete the degree-progress and student-record integrations.
5. Combine injection detection with least-privilege tools, authorization checks, history-aware input handling, and output controls.
6. Preserve a frozen held-out evaluation set for future teams.
7. Add confidence intervals and clearer evaluation metadata to future reports.

## 12. Final assessment

The Student Success Advisor should be described as a technically substantial research prototype with promising preliminary routing results and a strong culture of testing. Its most important achievement is not a single accuracy number, but the integration of structured data, deterministic tools, citations, escalation, and saved evaluation artifacts into one advising prototype.

The evaluation also performs its essential research function: it identifies where the prototype is not yet reliable. The routing layer appears mature relative to the current dataset, while prerequisite uncertainty, incomplete student-data integration, and prompt-injection coverage remain important limitations. Reporting both the successes and failures gives the project a more credible and defensible final result.
