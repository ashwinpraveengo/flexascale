# FLEXASCALE — FINAL COMPLETE PROJECT FINISHING MISSION

You are the lead engineer responsible for bringing my final-year B.Tech project, FlexaScale, to its final, fully functional, verified, presentation-ready state.

This is the final completion phase. I want you to take ownership of the entire existing project.

**My priority is not to prove that RL beats HPA at any cost. My priority is to complete the entire project properly, make every component work, verify the complete end-to-end system, create an exceptional dashboard, preserve and document the best genuine results, and prepare extremely simple and comprehensive learning documentation.**

You have engineering freedom to inspect, refactor, fix, train, test, improve, and reorganize the project wherever necessary.

Do not just provide suggestions or a plan. Work directly in the existing repository, implement improvements, run checks, and verify the actual outcomes.

---

# PART 1 — COMPLETE PROJECT AUDIT

Start by inspecting the entire repository.

Inspect:
- Source code and project architecture.
- Python environments and dependencies.
- GNN and PPO implementation.
- Training scripts and saved models.
- Alibaba datasets and preprocessing.
- Gymnasium simulator.
- Live metrics pipeline.
- Prometheus and Grafana.
- Kubernetes operator.
- Safety controller and HPA fallback.
- Helm releases and deployment configurations.
- All microservices.
- Locust workload generation.
- Dashboard frontend and backend APIs.
- Benchmark scripts and raw experiment data.
- Existing reports, logs, and documentation.
- Git status and uncommitted changes.

Establish exactly:
1. What is implemented.
2. What is working.
3. What is partially working.
4. What is broken.
5. What is not yet implemented.
6. What needs improvement.
7. What can be safely preserved.

Do not assume that an earlier successful test proves that the entire project works today.

Preserve valuable existing code, datasets, checkpoints, experiment results, and working configurations.

# PART 2 — VERIFY THE COMPLETE FLEXASCALE SYSTEM END TO END

This is the highest-priority technical requirement.

Verify the complete flow:

**Metrics → State Aggregation → Service Discovery → Dependency Graph → GNN → PPO → Decision → Safety Controller → Kubernetes Execution → New Metrics → Dashboard.**

For every component, verify its actual input, processing, output, and integration with the next component.

Check the following.

### 2.1 Metrics pipeline
- Prometheus scrapes the expected targets.
- CPU, memory, request rate, and latency metrics are collected where available.
- Metric names and labels are mapped correctly.
- Missing, stale, and zero-valued metrics are distinguished.
- Aggregation and sampling intervals are correct.
- Service observations correspond to the correct Deployments.

### 2.2 State aggregator
- The state vector has the expected shape.
- Features are in the correct order.
- Units and normalization match training.
- Missing values are handled safely.
- Discovered services map correctly to state entries.

### 2.3 Dependency graph and GNN
- The graph contains the correct service nodes.
- Dependencies and edges are constructed correctly.
- Node ordering remains consistent.
- The GNN actually participates in the intended inference path.
- Model input and output dimensions are correct.
- Topology limitations are documented.

### 2.4 PPO policy
- The intended trained model loads.
- The correct checkpoint is used.
- Observation preprocessing matches training.
- Actions are valid.
- Inference errors are handled safely.
- The live operator actually invokes the intended policy.
- A heuristic or fallback is not accidentally being reported as PPO.

### 2.5 Safety and execution
- Replica bounds are enforced.
- Cooldowns and hysteresis work.
- Invalid decisions are rejected.
- Missing telemetry causes safe behavior.
- Controller ownership is exclusive.
- HPA fallback works.
- Kubernetes scaling requests are applied correctly.
- Actual replica changes are verified.
- Failed operations are logged.
- Cleanup restores a safe cluster state.

Do not merely check whether functions exist. Test the complete integrated execution path.

---

# PART 3 — VERIFY AUTO MODE ESPECIALLY CAREFULLY

Auto mode is one of the most important features of my project.

I need to know whether Auto mode genuinely selects FlexaScale for some microservices and native HPA for others, based on the implemented decision rules.

**Do not assume that Auto mode is working just because the dashboard displays different ownership labels.**

Test the actual backend decision and Kubernetes execution.

Verify:

1. How Auto mode evaluates each microservice.
2. Which conditions cause it to select FlexaScale.
3. Which conditions cause it to select HPA.
4. Whether different microservices can have different owners simultaneously.
5. Whether FlexaScale actually receives control when selected.
6. Whether the RL policy is actually invoked for those services.
7. Whether the policy's proposed replica count is valid.
8. Whether the safety layer approves the action.
9. Whether Kubernetes receives the scaling request.
10. Whether the desired and ready replicas actually change.
11. Whether the controller ownership is correctly reflected in the dashboard.
12. Whether fallback to HPA happens correctly when FlexaScale is unhealthy or telemetry is unavailable.

Test scenarios where:
- FlexaScale is selected.
- HPA is selected.
- FlexaScale becomes unhealthy.
- Telemetry becomes stale or unavailable.
- SLA risk increases.
- Workload changes.
- Controller ownership needs to switch.

Provide evidence from logs, API responses, Kubernetes Deployment state, and actual scaling events.

For each tested scenario, record:

| Service | Selected owner | Decision reason | Policy invoked | Action applied | Actual replicas |
|---|---|---|---|---|---|

Make sure the distinction between these concepts is clear:

- Proposed replica count.
- Approved replica count.
- Desired replica count.
- Ready replica count.
- Actual controller owner.

Never claim FlexaScale controlled a service merely because its proposed replica count is displayed.

**Most importantly, demonstrate at least one verified scenario where Auto mode selects FlexaScale, invokes the intended policy, passes safety checks, and successfully applies a Kubernetes scaling decision.**

If a scenario does not trigger naturally, use a controlled, documented test configuration. Do not falsify the results or force a misleading production behavior.

---

# PART 4 — VERIFY ALL THREE CONTROLLER MODES

The project must support three distinct operating modes.

### Mode 1: Native HPA
Kubernetes' built-in Horizontal Pod Autoscaler controls the selected Deployments.

### Mode 2: FlexaScale
The GNN/PPO-based FlexaScale controller manages the selected Deployments through the safety and execution layer.

### Mode 3: Auto
The automatic decision system chooses between HPA and FlexaScale for individual services.

For all three modes, verify:
- Configuration.
- Controller ownership.
- Scaling behavior.
- Replica changes.
- Safety mechanisms.
- Logs and explanations.
- Dashboard representation.
- Cleanup and restoration.

HPA and FlexaScale must never actively control the same Deployment simultaneously.

Do not make the controller modes merely visual switches. They must correspond to real backend behavior.

The goal is to have a reliable working hybrid autoscaling system, even if native HPA performs better overall in some experiments.

---

# PART 5 — COMPLETE AND POLISH THE DASHBOARD

I want one of the best-looking dashboards possible for my final-year project presentation.

The existing dashboard should be improved substantially in both design and functionality.

Use the existing React, TypeScript, Vite, and Tailwind stack wherever appropriate.

Create a premium, modern cloud infrastructure control center with:
- Excellent typography.
- Strong visual hierarchy.
- Beautiful dark theme.
- Consistent design system.
- Professional spacing.
- Elegant cards.
- Interactive charts.
- Responsive layouts.
- Smooth animations.
- Clear status indicators.
- Polished loading and error states.
- No clipped numbers, overlapping elements, or broken tables.

The dashboard should impress a reviewer immediately while remaining easy to understand.

## 5.1 Overview

Show:
- Cluster health.
- Application health.
- Number of discovered services.
- Active controller mode.
- Request throughput.
- p50, p90, p95, and p99 latency where available.
- Error rate.
- SLA compliance.
- CPU and memory utilization.
- Desired and ready replicas.
- Recent scaling events.
- Estimated resource cost.

## 5.2 Live Lab

Make the Live Lab easy to operate during a presentation.

Allow:
- HPA mode selection.
- FlexaScale mode selection.
- Auto mode selection.
- Workload scenario selection.
- Locust user and spawn-rate configuration.
- Experiment start and stop.
- Live metrics monitoring.
- Actual shopping application access.
- Per-service scaling inspection.
- Experiment completion and result viewing.

All controls must work correctly.

Prevent duplicate experiments and unsafe controller transitions.

## 5.3 Auto Mode page

Create a particularly clear interface showing:
- Service names.
- Current controller owner.
- FlexaScale recommendation.
- HPA recommendation.
- Actual desired replicas.
- Ready replicas.
- CPU and memory.
- Latency and SLA indicators.
- Decision reasons.
- Controller health.
- Ownership transitions.
- Fallback events.

Clearly distinguish a recommendation from an applied scaling action.

## 5.4 Comparison page

Show HPA, FlexaScale, and Auto comparisons using valid saved experiment results.

Include:
- Throughput.
- Latency percentiles.
- Error rate.
- SLA violations.
- CPU and memory.
- Average and peak replicas.
- Replica-hours.
- Scaling events.
- Estimated cost.
- Resource efficiency.

Show the workload scenario and experiment configuration.

Do not fabricate savings or present incomparable experiments as a fair comparison.

## 5.5 Models page

Show:
- Model availability.
- Model version.
- Checkpoint path.
- Training status, if known.
- Inference health.
- Observation dimensions.
- Action dimensions.
- Topology compatibility.
- Errors and fallback information.

Use actual information from the model and backend.

---

# PART 6 — LIVE SCALING GRAPH ANIMATION

This is a mandatory feature suggested by my project guide.

Create an impressive animated **Live Kubernetes Scaling Visualization** that makes the actual scaling behavior visible while the workload is running.

This should be one of the standout features of the presentation dashboard.

### Main graph

- X-axis: time.
- Y-axis: replica count.
- Actual desired replicas.
- Actual ready replicas.
- HPA recommendation, where available.
- FlexaScale recommendation, where available.
- Scaling events as visible markers.

### Supporting live graphs

Show synchronized graphs for:
- Request rate.
- p50/p95 latency.
- CPU utilization.
- Memory utilization.
- Error rate.

### Animation

When traffic increases:
- The workload graph should visibly change.
- Metrics should update.
- The selected controller should make its decision.
- The decision should appear on the timeline.
- A scaling request should appear.
- The actual replica count should change when Kubernetes confirms it.
- Ready replicas should update when pods become ready.

Use smooth chart transitions without resetting the graph on every refresh.

Include:
- Hover details.
- Timestamps.
- Legend.
- Scaling event annotations.
- Current controller ownership.
- Pause/resume where appropriate.
- Historical experiment replay.

**Important:** Animate only what actually happens. A proposed action must not be presented as a completed scale-up or scale-down. Missing telemetry must appear as missing data, not fabricated values.

Make the graph visually outstanding but technically accurate.

---

# PART 7 — TELEMETRY AND METRIC CORRECTNESS

Investigate all dashboard metric inconsistencies.

Earlier, only the API gateway showed latency while other services showed missing latency.

Check:
- FastAPI instrumentation.
- Request counters.
- Request duration histograms.
- Prometheus scrape targets.
- PromQL queries.
- Metric labels.
- Aggregation windows.
- Dashboard API mappings.

Fix missing instrumentation or incorrect queries where appropriate.

Do not:
- Copy gateway latency to every service.
- Display fake zero values.
- Substitute estimates for actual observations without labelling them.
- Claim an SLA was met when the corresponding percentile exceeds the target.

Verify that p50, p90, p95, and p99 use consistent measurement windows and correct percentile calculations.

Make SLA status mathematically consistent with the displayed metric.

---

# PART 8 — TRAINING AND DATASET IMPROVEMENT

Inspect the existing Alibaba trace dataset, preprocessing pipeline, simulator, reward function, and saved models.

I have access to a laptop with a GPU for training and experiments.

Use GPU acceleration where it genuinely benefits training.

You may:
- Improve training configurations.
- Add representative workloads.
- Improve the reward function.
- Improve dependency graph construction.
- Improve model normalization.
- Train additional checkpoints.
- Evaluate alternative configurations.
- Add relevant microservices or synthetic topologies.
- Run ablation studies where useful.

However:
- Preserve the existing best checkpoint.
- Do not overwrite working models with unverified candidates.
- Do not assume more training means better performance.
- Evaluate candidate models before promoting them.
- Do not make beating HPA a requirement for declaring the project complete.
- Report the actual performance and limitations.

The main goal is a complete, reliable implementation rather than an artificially favorable research result.

---

# PART 9 — HELM AND INSTALLATION VERIFICATION

The current project uses Helm releases for:
- FlexaScale operator, chart 0.4.1.
- Shopping application, shopping-app 1.1.0.
- Monitoring, kube-prometheus-stack.

Verify:
- Installation.
- Configuration.
- Upgrade.
- Live-mode switching.
- Rollback.
- Uninstall.
- RBAC.
- Namespace selection.
- Prometheus integration.
- Application preservation.
- Persistent data preservation.
- Safe controller restoration.

The images are currently built locally inside Minikube and are not available in a public registry.

Preserve this workflow and accurately document how images must be built and loaded when deploying on a new cluster.

Do not claim universal installation without documenting image availability and prerequisites.

---

# PART 10 — FINAL RESULTS FOLDER

After completing the verification and benchmarking, create a dedicated folder:

`results/`

This folder must contain the strongest genuine and useful results from the project.

Do not copy every random experiment into it.

Select the best valid results, particularly scenarios where FlexaScale performs better than HPA on a clearly defined metric or workload.

For each selected result, provide:

- Experiment name.
- Workload scenario.
- Controller mode.
- Number of virtual users.
- Duration.
- Initial replica configuration.
- Relevant HPA configuration.
- FlexaScale configuration.
- Throughput.
- p50, p90, p95, and p99 latency.
- Error rate.
- CPU and memory utilization.
- Average and peak replicas.
- Replica-hours.
- Estimated cost.
- SLA status.
- Comparison with the equivalent HPA run.
- Explanation of why the result is interesting.
- Limitations and measurement conditions.

Include:
- Raw result references.
- Processed CSV or JSON where useful.
- Graphs and charts.
- Screenshots from the actual dashboard.
- Experiment explanations.

### Important selection rule

Only include results that actually exist and can be traced to valid experiment data.

If FlexaScale wins on latency but loses on cost, state that.

If FlexaScale wins only under a particular workload, explain the workload.

If no valid experiment demonstrates an advantage, do not invent a winning result. Include the strongest genuine results and explicitly explain their limitations.

Create:

`results/RESULTS.md`

This should be a well-organized report with:
1. Project result overview.
2. Best FlexaScale experiments.
3. Scenario-by-scenario explanations.
4. HPA comparisons.
5. Performance charts.
6. Resource-efficiency analysis.
7. Cost analysis.
8. SLA analysis.
9. Screenshots.
10. Limitations and conclusions.

Make the report easy to understand for an academic reviewer.

---

# PART 11 — COMPLETE PROJECT EXPLANATION FOR MY STUDIES

Create a dedicated documentation folder:

`docs/learning/`

I need to start studying and preparing for my project presentation and viva.

Create:

`docs/learning/FLEXASCALE_COMPLETE_EXPLANATION.md`

This must be an extremely comprehensive, beginner-friendly explanation of the entire project, from beginning to end.

**Assume I know very little about the difficult technical terminology. Explain everything in very simple English.**

Do not merely provide an abstract or a short summary.

Explain the entire execution flow in the order that the system works.

Cover:

### A. Fundamentals
- What is a microservice?
- What is Kubernetes?
- What is a pod?
- What is a Deployment?
- What is a replica?
- What is autoscaling?
- What is HPA?
- Why do we need FlexaScale?

### B. Complete architecture
Explain every component:
- Metrics pipeline.
- Prometheus.
- Grafana.
- Service discovery.
- State aggregation.
- State vector.
- Dependency graph.
- GNN.
- PPO.
- Reward function.
- Simulator.
- Safety controller.
- Kubernetes operator.
- HPA fallback.
- Dashboard.
- Locust.

For every term:
1. Give its simple meaning.
2. Explain why it is needed.
3. Explain what happens inside FlexaScale.
4. Give a practical example.
5. Explain how it connects to the next component.

### C. Data and machine learning
Explain:
- Alibaba Cluster Trace.
- Data preprocessing.
- Training data.
- State and action spaces.
- Reward.
- Policy.
- Agent.
- Environment.
- Episode.
- Step.
- Observation.
- Training versus inference.
- GNN nodes and edges.
- PPO actor and critic.
- Model checkpoints.
- Model evaluation.

Use small examples and avoid unnecessarily difficult language.

### D. Complete live execution flow

Explain precisely what happens when:
1. A user opens the shopping application.
2. Locust generates traffic.
3. Prometheus collects metrics.
4. The state aggregator builds observations.
5. The dependency graph is created.
6. GNN processes the graph.
7. PPO selects an action.
8. Safety checks the action.
9. Kubernetes changes replicas.
10. Pods become ready.
11. New metrics are collected.
12. The dashboard displays the result.

Explain the full feedback loop.

### E. Three controller modes

Explain HPA, FlexaScale, and Auto with simple examples.

Explain how Auto selects a controller for each service, how ownership works, how decisions are made, and what happens when a controller fails.

### F. Performance and evaluation

Explain:
- Throughput.
- Requests per second.
- Latency.
- p50, p90, p95, p99.
- Error rate.
- CPU utilization.
- Memory utilization.
- SLA and SLO.
- Replica-hours.
- Resource efficiency.
- Estimated cloud cost.
- Scaling delay.
- Oscillation.
- Recovery time.

Explain all important formulas using simple numerical examples.

### G. Results and limitations

Explain the actual benchmark findings, why HPA may perform better, where FlexaScale performs well, where it struggles, and what the experiments establish.

Use actual verified results rather than inventing favorable claims.

### H. Complete code walkthrough

Identify the important source files and explain:
- What each file does.
- Which functions are important.
- What each important function receives.
- What it returns.
- Which other component calls it.
- How the files connect to one another.

Prioritize the actual project files, not generic example code.

### I. Final presentation explanation

Give me a simple but technically accurate explanation I can speak during a project presentation.

Explain difficult terminology in easy language so I can confidently answer follow-up questions.

---

# PART 12 — COMPLETE DASHBOARD USER MANUAL

Create another dedicated document:

`docs/learning/FLEXASCALE_DASHBOARD_COMPLETE_GUIDE.md`

This must teach me how to operate the dashboard from beginning to end.

Assume I have never used the dashboard before.

Explain every page, section, metric, graph, button, control, and important label.

Cover:

### 1. Starting the dashboard
- Startup command.
- Prerequisites.
- Expected output.
- Dashboard URL.
- Shopping application URL.
- Prometheus and Grafana URLs.
- Health checks.
- Safe shutdown.

### 2. Overview page
Explain every card, metric, status, graph, and alert.

### 3. Live Lab
Explain:
- HPA mode.
- FlexaScale mode.
- Auto mode.
- Workload scenarios.
- User count.
- Spawn rate.
- Duration.
- Start and Stop.
- Experiment progress.
- Live metrics.
- Service-level data.

For every control, explain what happens in the backend when I use it.

### 4. Auto Mode page
Explain:
- Owner.
- FlexaScale proposal.
- HPA proposal.
- Actual replicas.
- Desired replicas.
- Ready replicas.
- Decision reason.
- Controller health.
- Ownership switching.
- Fallback.

Give practical examples.

### 5. Live scaling visualization
Explain every axis, line, marker, color, event, and animation.

Show how to interpret an actual scale-up and scale-down.

Explain the difference between a proposed action and an applied scaling event.

### 6. Comparison page
Explain how to compare HPA, FlexaScale, and Auto.

Explain each metric and what makes a result good or bad.

### 7. Service topology
Explain nodes, edges, dependencies, and service health.

### 8. Models page
Explain model status, checkpoint, inference, dimensions, and errors.

### 9. Results and experiment history
Explain how to find valid runs, interpret comparisons, and identify the best FlexaScale scenarios.

### 10. Practical operating examples

Give step-by-step instructions for:
- Running a steady browsing workload.
- Running a flash-sale spike.
- Running an HPA experiment.
- Running a FlexaScale experiment.
- Running an Auto experiment.
- Comparing results.
- Viewing actual scaling.
- Recovering safely after a failed experiment.

### 11. Troubleshooting

Explain what to do when:
- Metrics are missing.
- Latency is unavailable.
- Pods are not ready.
- HPA does not scale.
- FlexaScale does not make decisions.
- Auto selects HPA.
- Auto selects FlexaScale.
- A scaling action is rejected.
- Dashboard data is stale.
- Locust fails.
- Prometheus is unavailable.
- Controller ownership is stuck.

Make this a practical operating manual, not just a description.

---

# PART 13 — FINAL VERIFICATION AND CLEANUP

After implementation, run the complete relevant test suite.

Verify:
- All important services.
- All three controller modes.
- Actual FlexaScale execution in Auto mode.
- Actual Kubernetes scaling.
- Metrics and telemetry.
- Dashboard functionality.
- Animated live scaling visualization.
- Benchmark report generation.
- Results folder.
- Documentation completeness.
- Helm installation and rollback.
- Startup and shutdown scripts.
- Safe ownership restoration.

Do not modify tests just to obtain a passing result.

Preserve invalid experiments separately and explain why they were invalid.

Do not delete valuable raw datasets, models, checkpoints, or evidence.

Review Git status and ensure the repository contains the intended deliverables without accidental secrets, large temporary files, or unrelated modifications.

# PART 14 — FINAL DELIVERY REPORT

At the end, provide me with a clear final report:

1. What was already implemented.
2. What was fixed.
3. What was improved.
4. What was newly developed.
5. How the GNN/PPO path was verified.
6. Whether Auto mode genuinely invoked FlexaScale and applied scaling.
7. Which services were controlled by HPA and FlexaScale in the verification scenarios.
8. Whether actual replica changes were observed.
9. Whether all dashboard pages work.
10. Whether the live scaling animation works using real data.
11. Which tests passed and failed.
12. Which benchmark results were validated.
13. What is inside `results/`.
14. What is inside `docs/learning/`.
15. The exact startup and shutdown commands.
16. All remaining limitations.

Use these statuses:
- VERIFIED
- PARTIALLY VERIFIED
- NOT VERIFIED
- BLOCKED

Do not mark something verified merely because its code exists.

 

### 15. REPOSITORY CLEANUP — REMOVE UNNECESSARY FILES SAFELY

Perform a complete cleanup of the FlexaScale repository.

1. Identify unnecessary files and folders, including:
   - Unused source files, duplicate implementations, obsolete scripts and deprecated modules.
   - Temporary debugging files, scratch files and test artifacts.
   - Unused screenshots, duplicate reports and outdated generated outputs.
   - Redundant configuration files and unused dependencies.
   - Old logs, caches, build artifacts and temporary files.
   - Outdated documentation that conflicts with the current implementation.

2. Before deleting anything:
   - Check whether the file is imported, referenced, executed or required by another component.
   - Search the entire repository for references to it.
   - Check whether it is needed by Docker, Helm, Kubernetes, CI/CD, scripts or documentation.
   - Distinguish genuinely obsolete files from historical experiment records.

3. Remove confirmed unnecessary files and folders. Update all references, imports, scripts, configuration files and documentation affected by the cleanup.

4. Preserve important project assets:
   - Original datasets and processed datasets required for execution.
   - Trained model weights, checkpoints and configuration files.
   - Valid benchmark results and raw experiment data.
   - Kubernetes manifests, Helm charts and deployment configurations.
   - Required source code, tests, scripts and essential documentation.
   - Reproducibility information and historical results that support the project.

5. Organize the repository properly:
   - Keep valid results under `results/`.
   - Keep learning documentation under `docs/learning/`.
   - Keep source code in a clean, logical structure.
   - Separate invalid or incomplete experiments from valid results, with clear explanations.
   - Avoid storing duplicate generated files in multiple locations.

6. Check and update `.gitignore` to exclude unnecessary items such as caches, virtual environments, temporary files, local build artifacts and generated logs, without ignoring important project assets.

7. Remove unused Python packages and frontend dependencies only after verifying that they are not required. Update dependency files accordingly.

8. After cleanup:
   - Run tests and relevant validation scripts.
   - Verify imports and application startup.
   - Verify Docker builds and Helm/Kubernetes deployment workflows.
   - Verify dashboard and backend startup.
   - Verify all documented commands still work.
   - Check Git status and summarize every deletion, modification and preserved important asset.

**CRITICAL SAFETY RULE:** Never perform blind deletion, broad wildcard deletion or destructive cleanup. Do not delete datasets, trained models, valid experiment results or important historical records just because they appear old or large. If a file's purpose is uncertain, preserve it and report it for review rather than deleting it.

The objective is a clean, professional, maintainable repository with no unnecessary clutter, while preserving everything required to reproduce, demonstrate, study and evaluate FlexaScale.
---

# FINAL INSTRUCTION

This is my final-year project. I need the complete system, not isolated working components.

My priorities are:

1. Everything must work end to end.
2. Auto mode must genuinely be tested, especially cases where FlexaScale is selected and actually controls services.
3. The three controller modes must work correctly.
4. The dashboard must be visually exceptional and fully functional.
5. The live scaling graph must show genuine Kubernetes scaling behavior.
6. The `results/` folder must contain the strongest genuine, clearly explained results.
7. The complete project explanation must teach me everything in very simple words.
8. The dashboard guide must teach me how to operate every feature.
9. All tests, evidence, and documentation must be checked.

You have the freedom to improve the project wherever necessary. Make sensible technical decisions independently.

**Do not stop at a plan. Inspect, implement, train where justified, test, verify, document, and deliver the complete project.**
