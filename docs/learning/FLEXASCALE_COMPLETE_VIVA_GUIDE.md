# FlexaScale — Complete Viva Guide

*The study and examination companion to `docs/learning/FLEXASCALE_PROJECT_EXPLANATION.md`. That document explains the
system from zero; this one goes deeper: every term, code walkthroughs, every metric and every number in the results,
the research papers, the mistakes and bugs met along the way, and hundreds of examiner questions with answers.*

**Ground rules this guide follows.** Every number comes from a file in the repository and the file is named. Values are
labelled as **measured** (live cluster or Locust), **calculated** (derived from measurements), **estimated** (cost from
list prices), or **simulated** (application twin). Anything that could not be verified from the repository is marked
**unverified**. Where FlexaScale did not win, this guide says so.

---

## Contents

* [Part A — Glossary: every term in simple English](#part-a--glossary-every-term-in-simple-english)
* [Part B — Analogies for the difficult ideas](#part-b--analogies-for-the-difficult-ideas)
* [Part C — Code walkthroughs, line by line](#part-c--code-walkthroughs-line-by-line)
* [Part D — Every component: input, processing, output, why, and what if it were missing](#part-d--every-component)
* [Part E — Diagrams and flowcharts](#part-e--diagrams-and-flowcharts)
* [Part F — Results and metrics masterclass](#part-f--results-and-metrics-masterclass)
* [Part G — Research papers and novelty](#part-g--research-papers-and-novelty)
* [Part H — Mistakes, bugs, debugging and troubleshooting](#part-h--mistakes-bugs-debugging-and-troubleshooting)
* [Part I — Viva questions and answers](#part-i--viva-questions-and-answers)
* [Part J — Explaining the project in 2, 5, 10 and 15 minutes](#part-j--explaining-the-project-in-2-5-10-and-15-minutes)

---

## Part A — Glossary: every term in simple English

Alphabetical. "→" points to where the term matters in FlexaScale.

| Term | Simple meaning | In FlexaScale |
|---|---|---|
| **Ablation** | Remove one part of a system and measure the difference, to see what that part contributes | The no-graph policy (`use_graph=False`) → graph showed no measurable benefit |
| **Action** | What an RL agent does at one step | Replica change −1, 0, +1, +2, +3 for one service |
| **Action head** | The last layer that turns features into action scores | 64 → 5 logits |
| **Actor** | The part of an actor-critic network that chooses actions | 128 → 64 (tanh) → 5 |
| **Actor-critic** | An RL design with a decision network (actor) and a judging network (critic) | SB3 `ActorCriticPolicy` |
| **Adam** | A popular gradient-descent optimiser that adapts the step size per weight | Used by SB3 and the warm start |
| **Adjacency matrix** | A table with a 1 where node i connects to node j | 20 × 20, `A[i, j] = 1` if i calls j |
| **Advantage** | How much better an action was than expected in that state | GAE with γ 0.97, λ 0.95 |
| **Aggregation** | Combining many neighbours' messages into one | Mean over callees, mean over callers |
| **Allocated resources** | What the scheduler reserves (requests), whether used or not | vCPU-hours = ready replicas × 0.1 core × time |
| **Annotation** | A free-text key/value note on a Kubernetes object | `flexascale.io/original-min-replicas` stores the HPA bounds while frozen |
| **API (application programming interface)** | A defined way for programs to talk | Kubernetes API, the lab's `/api/lab/...` |
| **Argmax** | The position of the largest value | The action with the highest probability (live decision) |
| **Auto mode** | FlexaScale's per-service choice between itself and native HPA | `operator/auto_mode.py` |
| **Autoscaling** | Changing capacity automatically with load | Horizontal, replicas only |
| **Back-pressure** | Slowness of a downstream service making its callers slow | Why the call graph matters |
| **Baseline** | What a new method is compared against | Default HPA (70%, 300 s) and tuned HPA (350%, 60 s) |
| **Batch / mini-batch** | A group of samples used for one gradient step | 512 decisions per mini-batch |
| **Behaviour cloning (imitation)** | Training a network to copy a teacher's actions | Warm start from `limit_target(0.6/0.3)` |
| **Block (experimental design)** | A group of runs done back to back under the same conditions | 12 blocks × 4 arms in the v9 study |
| **Bucket (histogram)** | A range of values that a histogram counts | Latency buckets 5 ms … 10 s |
| **Burstiness** | How spiky traffic is | Feature 7: log₂(peak / mean rate over 5 min) |
| **cAdvisor** | The part of the kubelet that measures containers' CPU and memory | Source of `container_cpu_usage_seconds_total` |
| **Calibration** | Choosing a parameter by a rule fixed in advance | The tuned HPA target (350% / 250%) |
| **Call graph** | Which service calls which | 16 nodes, 25 edges |
| **Categorical distribution** | Probabilities over a fixed set of choices | Softmax over 5 actions |
| **Checkpoint** | Saved network weights at one point in training | `best_model.zip` |
| **Churn** | Changing replicas often | Reward term 0.25 per change |
| **Clip range (ε)** | PPO's limit on how far the probability ratio may move per update | 0.2 from scratch, 0.1 after warm start |
| **Closed-loop load** | Users wait for each response before the next request | Locust; a slow shop gets fewer requests |
| **Cluster** | A group of machines run by Kubernetes | Single-node Minikube |
| **Comparable start** | Every run starts from the same settled state | Data reset, all services at 1 ready replica |
| **Confidence** | The policy's probability of the action it chose | e.g. 0.4883 |
| **Confidence interval (95%)** | A range that would contain the true mean in 95% of repetitions | t-interval over pairs |
| **Confound** | A hidden factor that changes results and is mistaken for the effect | The laptop's power profile (v7 first batch) |
| **Container** | A packaged program with its dependencies | One per pod |
| **Controller (Kubernetes)** | A loop that makes the actual state match the desired state | HPA, Deployment controller, FlexaScale operator |
| **Cooldown** | A waiting time after an action before the next | 20 s after scale-up, 30 s after scale-down |
| **CPU limit / request** | Maximum CPU a container may use / CPU reserved for it | 500 m / 100 m |
| **Critic** | The network part that estimates how good a state is | 128 → 64 (tanh) → 1; training only |
| **Decision log** | One JSON line per service per step | `decisions.jsonl` |
| **Deployment** | "Keep N identical pods" | One per service |
| **Desired replicas** | The count Kubernetes was asked for (`spec.replicas`) | White line in the timeline |
| **Discount factor (γ)** | How much less a future reward counts | 0.97 per 10 s step |
| **Dwell** | Consecutive steps a new choice must persist before it takes effect | 2 steps before Auto hands a service to FlexaScale |
| **Embedding** | A list of numbers that summarises something for a network | 64 numbers per service |
| **Entropy** | How spread out a probability distribution is | Bonus 0.01 to keep exploring |
| **Episode** | One complete simulated run | 300–600 s of simulated load |
| **Exploitation / exploration** | Using the best-known action / trying others to learn | Argmax live / sampling in training |
| **Feature** | One input number | 10 per service |
| **Focal service** | The service a decision is being made for | One-hot vector of length 20 |
| **Freeze (HPA)** | Set an HPA's min = max so it cannot move replicas | Before FlexaScale scales a service |
| **GAE** | Generalised Advantage Estimation, a smoothed advantage | λ = 0.95 |
| **Gate** | A rule a new model must pass before deployment | v9 must beat v7 on validation: −2.47 vs −2.91 |
| **GNN** | Graph neural network: a network that passes information along a graph | `GraphFocalExtractor` |
| **Gradient clipping** | Limiting the size of a training step | Max norm 0.5 |
| **Gymnasium** | The standard Python interface for RL environments | `TwinEnv` |
| **Held-out test set** | Data never used for training or selection | T1, T2, T3 |
| **Helm / chart / release** | Kubernetes package manager / a package / an installed copy | `helm/flexascale` 0.5.1; release `flexascale` |
| **Hook (Helm)** | A job Helm runs at a lifecycle moment | Hand-back before upgrade/rollback/uninstall |
| **HPA** | Horizontal Pod Autoscaler, Kubernetes' built-in CPU-based autoscaler | Baseline and safety net |
| **Hysteresis** | Different thresholds or delays for switching on and off, to avoid flapping | Auto dwell; activation vs deactivation thresholds |
| **Inference** | Using a trained model (no learning) | Every 10 s on the cluster |
| **Ingress** | The HTTP entry point into a cluster | The shop's URL |
| **KL divergence** | A measure of how different two probability distributions are | `target_kl = 0.02` stops large updates |
| **kubectl** | The Kubernetes command-line tool | FlexaScale's `Kube` class wraps it |
| **Latency** | Response time | ms; mean and percentiles |
| **Latency inflation** | Latency relative to a service's own normal | Feature 3, reward term |
| **LayerNorm** | Normalises a vector to mean 0, variance 1 (with learned scale/shift) | In each message-passing round |
| **Lease** | A Kubernetes lock object with an owner and an expiry | `flexascale-shopping`, 30 s |
| **Logits** | Raw scores before softmax | 5 per decision |
| **Mask** | 1 for real items, 0 for padding | 20 node slots, 16 used |
| **Message passing** | Nodes exchanging and combining embeddings along edges | 2 rounds |
| **metrics-server** | Kubernetes component that gives the HPA its CPU numbers | 60 s resolution (second laptop) |
| **Microservice** | A small program doing one job over the network | 16 in the shop |
| **Minikube** | A one-machine Kubernetes for development | Profile `flexascale` |
| **Model card** | A JSON file describing a trained model | `models/flexascale_v9/model_card.json` |
| **Namespace** | A named folder inside a Kubernetes cluster | `flexascale-apps` |
| **Node (graph)** | One item in a graph | A service |
| **Node (Kubernetes)** | One machine in the cluster | One (Minikube) |
| **Observation** | The numbers the agent sees at one step | 660 per focal decision |
| **Observe mode / shadow mode** | FlexaScale computes and logs, changes nothing | Default mode |
| **On par / inconclusive** | The verdict when confidence intervals include zero | FlexaScale vs tuned HPA |
| **Operator** | A program that watches and changes Kubernetes objects | `AppOperator` |
| **Optimistic concurrency** | Updates succeed only if the object has not changed since read (`resourceVersion`) | Lease acquisition |
| **Oscillation** | A reversal of scaling direction | Counted per service per run |
| **Over-provisioning** | More capacity than needed | Wastes replica-hours |
| **p50/p90/p95/p99** | Percentiles: time below which 50/90/95/99% of requests finished | SLO is on p95 |
| **Pairing** | Comparing each candidate run with its own matched baseline run | Same block |
| **Pod** | The smallest unit Kubernetes runs | One service container |
| **Policy** | The decision rule | The neural network |
| **PPO** | Proximal Policy Optimization: RL with clipped, small updates | Stable-Baselines3 |
| **Pre-registration** | Writing the analysis rules before running the experiment | `docs/POLICY_V7.md`, `docs/POLICY_V9.md` |
| **Probability ratio (ρ)** | New probability ÷ old probability of an action | Clipped in PPO |
| **Prometheus / PromQL** | Time-series database / its query language | `rate(...[1m])` |
| **Proposal vs action** | What a controller *would* do vs what was *sent to Kubernetes* | Green dashed line vs ◆ marker |
| **Ready replicas** | Pods that passed their readiness check (`status.readyReplicas`) | Teal area in the timeline |
| **Receptive field** | How far in the graph a node's output can see | 2 hops |
| **Replica** | One copy of a service | 1–10 per service |
| **Replica-hours** | Ready replicas integrated over time, in hours | Primary cost measure |
| **Residual connection** | Adding a layer's input to its output | `h + ReLU(LN(z))` |
| **Return** | Discounted sum of future rewards | What PPO maximises |
| **Reward** | The score after an action | Penalty in replica-equivalents |
| **RBAC** | Role-based access control in Kubernetes | Read-only in observe, write verbs only in live |
| **Rollout** | A batch of experience collected before an update | 5,120 decisions |
| **Scale sub-resource** | The part of a Deployment that holds only its replica count | `kubectl scale` |
| **Scrape** | Prometheus pulling metrics from an endpoint | cAdvisor 10 s, services 15 s |
| **Seed** | The starting number of a random generator; same seed → same randomness | Seeds 1, 2 for training; fixed seeds for test sets |
| **ServiceMonitor** | A Prometheus Operator object that says what to scrape | One per shop service |
| **Settled start** | All services at their minimum and ready before the load begins | Validity rule |
| **SLA / SLO** | Agreement / objective on service quality | End-to-end p95 ≤ 1000 ms |
| **Softmax** | Turns scores into probabilities that sum to 1 | Over 5 actions |
| **Stabilisation window** | HPA uses the highest recommendation of the last N seconds before scaling down | 300 s default, 60 s tuned |
| **Stale telemetry** | Data older than allowed | > 120 s → no FlexaScale decision |
| **Step** | One decision moment | 10 s |
| **Throughput** | Completed requests per second | req/s |
| **Tolerance (HPA)** | Ignore changes when CPU is within ±10% of target | 0.1 |
| **Twin (application twin)** | A simulator fitted to measurements of the real application | `simulator/twin.py` |
| **Under-provisioning** | Less capacity than needed | Raises latency and errors |
| **Unit-free feature** | A ratio or log ratio, with no physical unit | All 10 features |
| **Validation set** | Data used to choose between models (not a fair test) | 40 twin workloads |
| **Value function V(s)** | Expected return from a state | The critic's output |
| **Watchdog** | A monitor that acts when something stops responding | `_check_operator`: restores HPAs |

---

## Part B — Analogies for the difficult ideas

**Kubernetes and replicas — a restaurant.** Each dish station (grill, salad, desserts) is a service; each cook at a
station is a replica. The manager (Kubernetes) keeps the number of cooks you asked for; if one leaves, another is hired.

**HPA — a rule-following floor manager.** Every 15 seconds they look at each station separately: "the grill cooks are
busier than 70% of their reserved effort, add cooks in proportion." They never notice that the dessert station is slow
because the fridge (database) is broken, and after a rush they keep the extra cooks for five more minutes, just in case.

**FlexaScale — an experienced manager who knows the kitchen's flow.** They know that a rush on main courses reaches
desserts later, that some stations are cheap to run and others expensive, and they make decisions for each station
while seeing the whole kitchen. But they are new, so a strict supervisor (the safety layer) checks every hiring decision,
and the rule-following manager stays in the building, ready to take over.

**Auto mode — a shift supervisor choosing who manages each station.** For every station, every 10 seconds: "Is the
experienced manager's information up to date? Are they confident? Is this station at risk, and does the rule-follower
want *more* cooks? If yes, give it to the rule-follower now. Otherwise, after two calm checks in a row, let the
experienced manager run it."

**Freezing the HPA — a key handover.** Only the person holding the station's key may change its staff. FlexaScale takes
the key by setting the HPA's range to exactly one number; it gives the key back by restoring the range written on the
key tag (the annotation).

**The Lease — the duty badge.** Only one FlexaScale manager can wear the badge for a restaurant, and it must be renewed
every shift (30 s). If they stop renewing, the badge expires and someone else can take it.

**Message passing — gossip along the corridors.** In the first round each station hears how its direct neighbours are
doing; in the second round it hears what *they* heard. After two rounds, the dessert station knows the grill is
overwhelmed even though they never talk directly.

**PPO clipping — a cautious driving instructor.** The learner may change their habits after each lesson, but never by
more than a small amount, so one lucky or unlucky lesson cannot ruin everything learned so far.

**Advantage — "better than usual".** Scoring 70 in an exam is great if you usually score 50 (positive advantage) and bad
if you usually score 90. PPO reinforces actions that did better than the critic expected.

**Percentiles — a queue at a ticket office.** p50 is how long the middle person waited; p95 is how long the person at
the 95th place in the "waiting time" ranking waited. Averages hide the few people who waited an hour; p95 and p99 do not.

**Replica-hours — renting chairs.** Two chairs for half an hour and one chair for an hour both cost one chair-hour.

**Pre-registration — writing the marking scheme before seeing the answers.** You cannot change the scheme afterwards to
favour the answer you like.

**A confound — the wrong reason for a win.** Two runners race on different days; one wins, but on their day there was a
tailwind. FlexaScale's apparent win in the first v7 batch came from the laptop running faster (power profile) whenever
FlexaScale was active, not from better scaling.

---

## Part C — Code walkthroughs, line by line

Each snippet is copied from the repository (sometimes shortened with `…`). Read the code, then the numbered notes.

### C.1 Turning telemetry into features — `rl/features_v3.py`, `FeatureTracker.update`

```python
ready_n = max(1, int(ready))                                                    # 1
cpu = None if cpu_cores is None else float(cpu_cores) / ready_n / max(cpu_limit, 1e-6)   # 2
x = np.zeros(F, dtype=np.float32)                                               # 3
x[0] = 0.0 if cpu is None else cpu                                              # 4
prev = self.prev_cpu.get(service)
x[1] = 0.0 if (cpu is None or prev is None) else cpu - prev                    # 5
…
old = [r for t, r in h if now - t >= 0.75 * TREND_S]                            # 6
if rps is None or not old:  x[2] = 1.0
else:
    base = old[-1]
    x[2] = (3.0 if rps > 0 else 1.0) if base <= 0 else float(rps) / base         # 7
rates = [r for _, r in h]
mean = sum(rates) / len(rates) if rates else 0.0
x[7] = math.log2(max(rates) / mean) if rates and mean > 0 else 0.0              # 8
…
if latency_ms and lh:
    base_lat = min(v for _, v in lh)                                            # 9
    x[3] = math.log2(max(latency_ms, 1e-3) / max(base_lat, 1e-3))
x[4] = min(1.0, desired / max(1, self.max_replicas))                            # 10
x[5] = min(1.0, ready / max(1, desired))
if cpu_cores is not None and rps is not None and rps > 1.0:
    est = 1000.0 * float(cpu_cores) / float(rps)                                # 11
    self.cpr[service] = est if service not in self.cpr else 0.8 * self.cpr[service] + 0.2 * est
c = self.cpr.get(service)
x[6] = 0.0 if not c else math.log10(max(c, 1.0)) / 3.0
x[8] = min(1.0, (now - self.last_up.get(service, -1e9)) / 60.0)                 # 12
x[9] = min(1.0, (now - self.last_down.get(service, -1e9)) / 60.0)
return np.clip(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), LOW, HIGH)   # 13
```

1. Never divide by zero ready pods.
2. Cores per ready pod as a fraction of the CPU **limit** (`None` stays `None` when telemetry is missing).
3. Ten zeros to fill.
4. Missing CPU becomes 0 here, but the operator never lets a service with missing CPU be owned by FlexaScale (guard 0).
5. Trend = change since the previous decision (10 s ago).
6. Request-rate samples at least 45 s old (0.75 × 60 s).
7. Rate now ÷ rate ~60 s ago; if the old rate was 0 and traffic appears, the maximum 3 is used.
8. Burstiness over the 5-minute history (`BURST_S = 300`).
9. Baseline latency = the lowest latency seen in the last 30 minutes (`BASELINE_S = 1800`); inflation is log₂ of the
   ratio, so 2× slower = 1.0, 4× slower = 2.0.
10. Replica fraction and readiness.
11. CPU-milliseconds per request, smoothed with an exponential moving average (80% old, 20% new), only when there is
    real traffic (> 1 req/s). This "includes idle share": at low traffic it overestimates per-request cost.
12. Time since last scale-up / scale-down, saturating at 60 s.
13. Clean up NaN/∞ and clip every feature to its trained range.

### C.2 Packing the graph — `features_v3.pack`

```python
idx = {s: i for i, s in enumerate(services)}               # services already sorted by the caller
x = np.zeros((n_max, F)); for s in services: x[idx[s]] = features[s]
adj = np.zeros((n_max, n_max))
for u, v in edges:
    if u in idx and v in idx and u != v: adj[idx[u], idx[v]] = 1.0   # caller row, callee column
mask = np.zeros(n_max); mask[: len(services)] = 1.0
return np.concatenate([x.ravel(), adj.ravel(), mask])       # 200 + 400 + 20 = 640 numbers
```

Edges to services that are not present (or self-loops) are ignored, so a partially discovered application still packs.

### C.3 Message passing — `rl/graph_policy.py`, `GraphExtractor.embed`

```python
x, adj, mask = _unpack(obs, self.n_max)                     # (B,20,10), (B,20,20), (B,20)
m = mask.unsqueeze(-1)                                      # (B,20,1) for broadcasting
h = torch.relu(self.inp(x)) * m                             # 10 → 64, padded rows forced to 0
deg_out = adj.sum(-1, keepdim=True).clamp(min=1.0)          # number of callees (≥1)
deg_in  = adj.sum(-2).unsqueeze(-1).clamp(min=1.0)          # number of callers (≥1)
for k in range(self.rounds):                                # 2 rounds
    z = self.self_w[k](h)                                   # own message (with bias)
    z = z + self.callee_w[k](torch.bmm(adj, h) / deg_out) \
          + self.caller_w[k](torch.bmm(adj.transpose(1, 2), h) / deg_in)
    h = (h + torch.relu(self.norm[k](z))) * m               # residual + LayerNorm + ReLU, keep padding at 0
pooled = (h * m).sum(1) / m.sum(1).clamp(min=1.0)           # mean over real services
```

`torch.bmm` is a batched matrix multiply: `adj @ h` gives, for each service, the **sum** of its callees' embeddings;
dividing by the out-degree makes it a **mean**. The transpose swaps rows and columns, so the same operation gives the
mean over callers.

`GraphFocalExtractor.forward` then does:

```python
graph, focal = obs[:, :-self.n_max], obs[:, -self.n_max:]   # 640 | 20-number one-hot
h, _, pooled = self.embed(graph)
own = (h * focal.unsqueeze(-1)).sum(1)                       # picks the focal service's row
return torch.cat([own, pooled], dim=1)                       # 128 numbers
```

### C.4 Running the model live — `rl/policy_runtime.py`, `predict_graph`

```python
services = sorted(features)
obs = features_v3.pack(features, services, edges, self.n_max)            # 640
if self.focal:
    batch = np.concatenate([np.repeat(obs[None, :], len(services), axis=0),
                            np.eye(self.n_max, dtype=np.float32)[: len(services)]], axis=1)  # 16 × 660
    rows = self._distribution_probs(batch)[0]                              # 16 × 5 probabilities
…
for i, s in enumerate(services):
    p = probs[i][0]
    a = int(torch.argmax(p).item())                                       # most likely action
    actions.append(a); confs.append(float(p[a].item()))                   # its probability = confidence
```

`_distribution_probs` calls `model.policy.get_distribution(obs)` inside `torch.no_grad()` (no gradients, inference
only). One batched forward pass decides all 16 services.

### C.5 The guards and ownership — `operator/app_operator.py`, `_decide` (core lines)

```python
telemetry_ok = m.cpu_pct is not None and not m.stale
if not telemetry_ok:
    reasons.append("telemetry_unavailable" if m.cpu_pct is None else "telemetry_stale")
    proposed, owner = current, ControlMode.HPA                            # never act blind
else:
    delta = max(-p.max_scale_down_step, min(p.max_step, self._delta(action, output, idx)))
    proposed = max(lo, min(hi, current + delta))
    record["policy_replicas"] = int(proposed)                             # the policy's own proposal
    if proposed > current and self._planned_total + (proposed - current) > p.max_total_replicas: …budget…
    if proposed > current and workload.ready_replicas < current: proposed = current  # wait for readiness
    if proposed > current and now - self._last_scale_up.get(name, -inf) < p.scale_up_cooldown_seconds: …
    if proposed < current:
        if cpu >= p.scale_down_block_cpu_pct: …blocked_cpu…
        elif memory >= p.scale_down_block_memory_pct: …blocked_memory…
        elif slo and latency > slo: …blocked_slo…
        elif now - self._last_scale_down.get(name, 0) < p.scale_down_cooldown_seconds: …cooldown…
        elif workload.ready_replicas < current: …waiting_for_readiness…
    if self.arbiter is not None:                                          # Auto mode
        dec = self._auto(...); owner = RL if dec.owner == "flexascale" else HPA
    elif …confidence gate with hysteresis…
```

Note the order: the policy's proposal is clipped and recorded *before* safety (so the log shows what the policy wanted),
then safety, then ownership. Execution (end of `_decide`): lock → `freeze_hpa` → `scale_deployment` if changed; or
release → `ensure_hpa_active` when handing back.

### C.6 Auto's hysteresis — `AutoArbiter.decide`, inner function `done`

```python
def done(owner, rule, reason, immediate):
    if owner == prev:                     final, streak = owner, 0            # no change
    elif immediate:                       final, streak = owner, 0            # safe direction: switch now
    else:
        cand, n = self._pending.get(service, (owner, 0))
        n = n + 1 if cand == owner else 1                                     # count consecutive choices
        self._pending[service] = (owner, n)
        if n >= cfg.dwell_steps:          final, streak = owner, n            # switch after 2
        else:                             final, streak = prev, n             # keep old owner for now
            reason += f" (waiting {n}/{cfg.dwell_steps} steps before switching)"
    self._owner[service] = final
```

Example: a service is with HPA; step 1 rule 4 chooses FlexaScale → "waiting 1/2"; step 2 again → FlexaScale takes over.
If on step 2 rule 3 had fired instead, the pending switch is cancelled and the service stays with HPA immediately.

### C.7 Freezing an HPA — `safety/hpa_manager.py`, `freeze_hpa`

```python
hpa = self.find_hpa(service_id)                                    # by scaleTargetRef
annotations = {ANNOTATION_FROZEN_BY: self.holder}
if not hpa.frozen:                                                 # record originals only once
    annotations[ANNOTATION_ORIGINAL_MIN] = str(hpa.min_replicas)
    annotations[ANNOTATION_ORIGINAL_MAX] = str(hpa.max_replicas)
patch = {"metadata": {"annotations": annotations},
         "spec": {"minReplicas": int(target), "maxReplicas": int(target)}}
res = self.kube.patch("hpa", hpa.name, self.config.namespace, patch)   # kubectl patch --type merge
```

Why "only once": if FlexaScale freezes an already-frozen HPA at a new count, the original 1–10 must not be overwritten by
the frozen value. Restoring reads the annotations back and sets them to `null` (a merge patch with `null` deletes a key).

### C.8 Percentiles from buckets — `metrics/workload_metrics.py`, `histogram_quantile`

```python
buckets = sorted(buckets, key=lambda b: b[0]); total = buckets[-1][1]   # +Inf bucket holds the total
rank = q * total
prev_bound, prev_count = 0.0, 0.0
for bound, count in buckets:
    if count >= rank:
        if bound == float("inf"): return prev_bound                      # capped: true value unknown
        return prev_bound + (bound - prev_bound) * (rank - prev_count) / (count - prev_count)
    prev_bound, prev_count = bound, count
```

### C.9 Replica-hours and cost — `evaluation/cost.py`, `summarize_resources`

```python
for cur, nxt in zip(ordered, ordered[1:]):               # consecutive 5 s samples
    dt = nxt["t"] - cur["t"]
    for svc in cur["services"].values():
        ready = int(svc.get("ready") or 0)
        rep_s       += ready * dt                         # replica-seconds
        cpu_alloc_s += ready * svc["cpu_request_cores"] * dt
        mem_alloc_s += ready * svc["memory_request_bytes"] * dt
        cpu_used_s  += svc["cpu_cores"] * dt              # observed (if known)
replica_hours = rep_s / 3600
estimated = alloc_cpu_h * 0.04048 + alloc_gib_h * 0.004445
```

A **left Riemann sum**: a sample's state is assumed to hold until the next sample. Uses **ready** replicas (what serves
and costs), and **requested** CPU/memory (what is reserved).

### C.10 Stability — `scaling_stability`

```python
for series in replica_series.values():                    # one desired-replica list per service
    last_dir = 0
    for a, b in zip(series, series[1:]):
        if b == a: continue
        changes += 1
        direction = 1 if b > a else -1
        if last_dir and direction != last_dir: reversals += 1
        last_dir = direction
```

So a service going 1→2→1 has 2 scaling events and 1 oscillation, however far apart the two changes are.

### C.11 The reward split — `simulator/twin_env.py`, `per_service_rewards`

```python
repl  = (d - floor).mean(axis=0)                          # each service's replicas above minimum
churn = |changes| per service
penalty = 6·p95_inflation + 10·slo_fraction + 5·failure_pct   # the shared latency/error penalty
contrib = (min(1, λ_i / e2e_rps) · own_excess_i).mean()   # share of traffic × own excess latency
share = contrib / contrib.sum()   (equal shares if nobody has excess)
return −0.1 × (1.0·repl + 0.25·churn + share·penalty)
```

The per-service rewards sum to the global reward, so optimising each service's own reward still optimises the
application's.

---

## Part D — Every component

| Component | Input | Processing | Output | Why it exists | Without it |
|---|---|---|---|---|---|
| Shop services | HTTP requests | Business logic, DB calls | Responses; `/metrics` | The system under control | Nothing to scale |
| Locust | Scenario, users, spawn rate, duration | Simulated user journeys | Load; stats CSVs | Repeatable, comparable load | No fair comparison |
| Prometheus | Scrapes | Stores time series; PromQL | Rates, sums, buckets | Measurement | FlexaScale is blind |
| Discovery | Kubernetes API | Filter by label/exclusions; find HPAs | `WorkloadInfo` list | Application-agnostic | Hard-coded service names |
| Telemetry client | PromQL results | Per-pod → per-Deployment; handle double counting, pod-level CPU, zero vs missing | `WorkloadMetrics` | Correct, honest inputs | Wrong or invented numbers |
| FeatureTracker | Telemetry + replica counts + time | Ratios, trends, histories | 10 features per service | Same inputs as in training | Train/live mismatch |
| Topology | Policy file (or traffic inference) | Edges restricted to discovered services | Edge list | Dependency awareness | No graph information |
| GNN extractor | 660 numbers | Embedding + 2 message-passing rounds + readout | 128 numbers | Combine neighbours' state | Each service decides alone |
| PPO actor | 128 numbers | MLP + softmax | 5 probabilities | The decision | No learned decision |
| Safety guards | Proposal + telemetry + history | Clip/block | Approved count + reasons | Bound the damage of a wrong decision | Unsafe scaling |
| Auto arbiter | Both proposals + health + risk | Ordered rules + dwell | Owner + rule + reason | Use each controller where it is safe and efficient | All-or-nothing control |
| Lease | Identity | Create/replace with resourceVersion | Exclusive application control | One FlexaScale per app | Two operators fight |
| HPA freeze/restore | Target count / annotations | `kubectl patch hpa` | HPA held or restored | HPA and FlexaScale never fight | Replica tug-of-war |
| Scaler | Approved count | `kubectl scale` | New `spec.replicas` | The actual change | Proposals only |
| Decision log | Each decision | JSON lines | `decisions.jsonl` | Explainability, evidence | No audit trail |
| Watchdog | Operator process + status file age | Restore all HPAs | Fallback event | Crashes/hangs cannot leave HPAs frozen | Frozen HPAs after a crash |
| Lab | Experiment request | Comparable start, run, sample, cleanup, summary | Run folder | Repeatable experiments | Manual, error-prone runs |
| Lab server | HTTP | JSON API | Data for the dashboard | One place to operate | Command line only |
| Dashboard | API JSON | Charts and tables | Visual control center | Watch and explain live | Raw logs only |
| Twin | Fitted parameters + workload | Queueing simulation | Simulated metrics | Fast, safe training | Months of risky live training |
| PPO training | Twin experience | Clipped policy updates | Trained weights | Learn the policy | No model |
| Helm chart | Values | Templates | Installed operator + RBAC + hook | Installable add-on | Manual installation |

---

## Part E — Diagrams and flowcharts

### E.1 Sequence of one operator step (live, Auto)

```
Operator            Kubernetes API         Prometheus          Policy (GNN+PPO)      Auto + guards
   │ renew Lease ───────▶│                       │                     │                     │
   │ list deployments,hpa▶│                       │                     │                     │
   │ PromQL (batched) ───────────────────────────▶│                     │                     │
   │◀────────────── per-pod CPU, mem, rps, buckets│                     │                     │
   │ features ×16, pack, 16 focal rows ─────────────────────────────────▶│                     │
   │◀────────────────────────────────────────────── probs 16×5 ─────────│                     │
   │ for each service: proposal → guards → owner ─────────────────────────────────────────────▶│
   │◀────────────────────────────────────────────────────────────── approved, owner, reasons ──│
   │ if FlexaScale & changed: patch hpa (min=max=n) ▶│                                          │
   │                          scale deployment n ───▶│                                          │
   │ if HPA & was frozen: restore hpa bounds ───────▶│                                          │
   │ append decisions.jsonl; write status.json                                                │
```

### E.2 Auto rules flowchart

```
            ┌───────────────────────────────┐
            │ model? CPU fresh? Lease held? │── no ──▶ HPA now  (controller_health)
            └──────────────┬────────────────┘
                          yes
            ┌──────────────▼────────────────┐
            │ confidence ≥ threshold?       │── no ──▶ HPA (policy_confidence)
            └──────────────┬────────────────┘
                          yes
            ┌──────────────▼────────────────┐
            │ (latency > SLO or CPU ≥ risk) │── yes ─▶ HPA now  (sla_risk)
            │  and HPA wants MORE replicas? │
            └──────────────┬────────────────┘
                           no
                           ▼
              FlexaScale (efficiency), after 2 consecutive steps
```

### E.3 Training pipeline

```
live calibration runs ─▶ fit_twin.py ─▶ twin (shopping_v9.json) ─▶ check vs live (2.0% RH, 8.9% p95)
                                                 │
            rule family limit_target(t/d) ─▶ best on validation: (0.6/0.3) ─▶ imitation warm start
                                                 │
                         PPO on 4 sims × 20 agents, 2M agent-steps, eval every 250k
                                                 │
              best checkpoint per run ─▶ select best run (focal_bc_s2, −2.466) ─▶ gate vs v7 (passed)
                                                 │
                          promote: model card + sha256 ─▶ policy files ─▶ live evaluation
```

### E.4 Data and evidence flow of an experiment

```
Locust CSVs ─┐
telemetry ───┼─▶ run.json (samples, events, summary, cleanup) ─▶ live_benchmark_summary.csv ─▶ benchmark (pairs, CI)
decisions ───┘                                                    │                          ─▶ dashboard Comparison
                                                                  └─▶ analyze_v7.py ─▶ reports/v9/evaluation.json/md
                                                                                    ─▶ build_results.py ─▶ results/
```

---

## Part F — Results and metrics masterclass

### F.1 Five kinds of number — always say which one you mean

| Kind | Definition | Examples in FlexaScale |
|---|---|---|
| **Measured (live Kubernetes)** | Read from the real cluster or Kubernetes API | desired/ready replicas, HPA bounds, pod CPU from cAdvisor |
| **Measured (load generator)** | Recorded by Locust from the user's side | requests, failures, end-to-end percentiles, throughput |
| **Calculated** | Computed from measured values by a formula in the code | replica-hours, CPU % of request, Δ%, confidence intervals, SLO-violation seconds |
| **Estimated** | Uses an assumption that is not measured | cost in USD (AWS Fargate list prices × allocated resources) |
| **Simulated** | Produced by the application twin or older simulators | rewards, T1/T2/T3 tables, validation scores, simulated replica-hours |

A sentence like "FlexaScale saves 7.7%" is incomplete. The complete version: "In the pre-registered live evaluation on
the second laptop, FlexaScale Auto used 7.7% fewer replica-hours (calculated from measured ready replicas) than the
default HPA, mean of 11 pairs, 95% CI −12.3% to −3.2%."

### F.2 The metric encyclopedia

Each entry follows the same twelve points: **(1)** name and definition, **(2)** what it measures and why it matters,
**(3)** formula and a calculation, **(4)** raw data, **(5)** generated by, **(6)** high vs low, **(7)** better, **(8)**
influence on autoscaling, **(9)** use for FlexaScale, **(10)** our values, **(11)** HPA vs FlexaScale vs Auto, **(12)**
limitations.

---

#### M1. Total, completed (successful) and failed requests

1. *Total requests*: every request Locust sent and got a result for during the run. *Failed*: those Locust marked as
   failures (HTTP error status, connection error, timeout, or an explicit failure in the user code). *Completed
   successfully* = total − failed (not stored as its own column).
2. The amount of work done and how much of it went wrong. With closed-loop users, a slower shop completes fewer requests.
3. From Locust's `Aggregated` row: `Request Count`, `Failure Count`. Example (run `20261031-035531`): 3,925 requests, 211
   failures → 3,714 succeeded.
4. Locust's HTTP client, per request.
5. `locust_stats.csv` → `read_locust_final()` → `summary.workload.total_requests/total_failures`;
   `results/data/selected_runs.csv` columns `total_requests`.
6. High totals at the same users = the shop kept up. High failures = errors, contention or timeouts.
7. Total: higher (same load). Failures: lower.
8. Not an input to any controller. An *outcome*.
9. Evaluates whether savings cost reliability.
10. E1 (25 users, 300 s): default HPA 4,695, tuned HPA 4,838, Auto 5,084 requests (Auto served more because it was faster). Verification
    runs at 40 users: 3,925–4,825 requests.
11. In v9 the failure rate differences were small (Auto +0.09 pp vs default HPA, CI includes 0).
12. Totals depend on duration and users, so compare only paired runs. Failures in the shop include *business* failures
    (declined payments in `payment_degradation`, 400s from empty carts in flash sales), not only overload.

#### M2. Error rate (failure rate), success rate, timeouts

1. *Failure rate* = failed ÷ total × 100 (Locust, end to end). *Service error rate* = 5xx responses per second per
   service (Prometheus). *Success rate* = 100 − failure rate.
2. Reliability as seen by users.
3. `failure_rate_pct = 100 × 211 / 3925 = 5.38%` (run `035531`). Per service: `error_rate = Σ rate(http_requests_total
   {status=~"5.."}[1m])`.
4. Locust results; service counters.
5. `read_locust_final`; `WorkloadMetricsClient.collect` (`error_rate`).
6. High = users see errors.
7. Lower.
8. Not a controller input (the reward in the twin charges 5 × failure %; the dashboard alerts at > 5% 5xx).
9. Check C3 of the verdict: failures not worse.
10. v9 arms: 0.29% (default HPA), 0.25% (tuned), 0.34% (RL), 0.32% (Auto). Verification at 40 users: 0.99%–7.08%.
11. No statistically supported difference in v9.
12. **Timeout rate is not a separate metric** in this repository: Locust counts a timed-out request as a failure; the
    twin counts requests above 10 s as failures. Success rate is only derivable (also a placeholder column in the Alibaba
    CSV, always 1).

#### M3. Throughput, RPS, request rate

1. *Throughput* = completed requests per second (Locust `Requests/s`). *Per-service request rate* = requests per second
   reaching a service (Prometheus).
2. How much work flows. Per-service rate shows where the load goes (the gateway sees every request; promotion only some).
3. Whole run: Locust's `Requests/s` (total requests ÷ Locust's own elapsed time); E1 Auto: 5,084 requests → 16.95 req/s (≈ 300 s of load). Per service:
   `max by (pod)(sum by (pod, job)(rate(http_requests_total[1m])))`, summed over pods.
4. Locust; service counters.
5. `read_locust_final/history`; `WorkloadMetricsClient.collect`.
6. High = more work done (good *if* the offered load is the same).
7. Higher at equal load (verdict check C4: mean ≥ −2%).
8. Feature 2 (`rps_trend`), feature 6 (CPU per request) and feature 7 (burstiness) use it.
9. Shows whether a controller slowed the shop down.
10. v9 means: 15.13 (default), 15.37 (tuned), 15.07 (RL), 15.15 (Auto) req/s; Auto vs default −1.4% [−4.5, +1.6].
11. Essentially equal.
12. Closed-loop: throughput falls when latency rises, so a controller can look "efficient" by being slow. Always read it
    with latency.

#### M4. Concurrent users, spawn rate, workload intensity

1. *Users* = simultaneous Locust virtual users; *spawn rate* = users started per second; *workload intensity* is set by
   users, the scenario's mix and its shape.
2. The offered load.
3. Flash sale at 25 users: 5 users (20%) → 25 → 5.
4. Locust history `User Count`.
5. `scenarios.py`; `read_locust_history` (`users` in each sample).
6. More users = more load.
7. Neither: it is a controlled input.
8. Not a controller input.
9. Must be identical within a pair.
10. Benchmarks: 25 users, spawn 5/s, 300 s. Verification: 40 users. Above ~40 users the single node runs short of
    memory.
11. —
12. At 25 users most services never need more than one replica, which limits any controller's possible saving.

#### M5. Mean (average) latency

1. Sum of response times ÷ number of requests.
2. Typical speed, but sensitive to outliers.
3. Locust `Average Response Time`. Per service: `1000 × rate(duration_sum[1m]) / rate(duration_count[1m])`. Example from
   the explanation: 20 requests with one at 1,200 ms → mean 99.9 ms while the median is ~20 ms.
4. Locust; service histograms' `_sum` and `_count`.
5. `read_locust_final` (`mean_latency_ms`); `collect` (`latency_mean_ms`).
6. High = slow.
7. Lower.
8. Feature 3 (latency inflation) uses per-service mean latency; scale-down block on SLO (if set); Auto rule 3 (if an SLO
   is set).
9. Context.
10. v9: 85 (default), 71 (tuned), 110 (RL), 94 ms (Auto).
11. RL and Auto had higher means, driven by tail events.
12. A few very slow requests dominate. Use percentiles for user experience.

#### M6. Latency percentiles p50, p90, p95, p99 (and Locust's others)

1. pX = the time below which X% of requests completed. Locust also reports 66%, 75%, 80%, 98%, 99.9%, 99.99%, 100% and
   max.
2. User experience across the distribution; p95 is the SLO metric; p99 shows rare stalls.
3. Sort times, take the value at position X% (Locust); interpolate in histogram buckets (Prometheus, Part C.8).
4. Locust per-request timings (end to end); service histograms (per service).
5. Whole run: `locust_stats.csv`; ~10 s windows: `locust_stats_history.csv`; per service: `histogram_quantile`.
6. High = slow tail.
7. Lower.
8. Feature 3 uses the mean, not percentiles. The SLO violation is measured on the window p95.
9. C2 of the verdict (p95 not worse).
10. v9 means: p50 44/42/37/37 ms; p95 241/167/395/200 ms; p99 838/510/1674/1936 ms (default/tuned/RL/Auto).
11. FlexaScale had the **lowest median and the highest tail**: lean replica counts are fast in the common case, but a
    burst that arrives before a scale-up is slow.
12. Locust rounds above 100 ms to two significant figures (130, 170, 5300), so +6% may be one rounding step. Histogram
    percentiles are interpolations and are capped at 10 s ("≥"). The mean of p95 over runs is not the p95 of all
    requests. Three late v9 reruns (memory pressure) dominate the RL p95 mean (sensitivity: +3.8% without them).

#### M7. SLO / SLA metrics

1. *SLO*: end-to-end p95 ≤ 1000 ms in each ~10 s Locust window. *e2e_slo_violation* (per 5 s sample): window p95 > 1000.
   *e2e_violation_seconds*: total time in violated samples. *e2e_violation_fraction*: violated samples ÷ samples with a
   p95. *service_violation_seconds*: time any service's mean latency exceeded its own SLO (0 for the shop: no per-service
   SLO). *SLA status* in `results/`: whole-run p95 ≤ 1000 → "met".
2. How long users had a bad experience.
3. `Σ Δt` over samples with `e2e_slo_violation`; E1 default HPA: 30 s (6 samples of 5 s).
4. Locust history CSV, sampled every 5 s.
5. `Experiment._sample` (flag), `_finalize` (sums).
6. High = long bad periods.
7. Lower (verdict check C5: mean ≤ +5 s).
8. In the twin the reward charges 10 × violation fraction.
9. Shows whether savings hurt users.
10. v9 means per run: 22.9 s (default), 8.0 (tuned), 25.6 (RL), 15.7 (Auto). E1: 30 s vs 0 s (Auto); E2: 115 s vs 30.1 s
    (RL).
11. Auto better than default, worse than tuned; RL about equal to default.
12. Window-based (a 10 s Locust window), so short spikes count fully. The dashboard's "SLA" is this SLO, not a contract.

#### M8. Recovery time / longest violation

1. Comparison page row "Longest violation (recovery)": the longest run of consecutive violated samples. In the twin,
   `recovery_s` = seconds from the first load drop until total desired replicas are within 1 of the run's minimum.
2. How quickly the system returns to normal.
3. Count consecutive violated samples × 5 s; twin: first tick after the drop with replicas ≤ floor + 1.
4. Samples; twin logs.
5. Dashboard compare; `twin_control.recovery_time`; `evaluation.json` arms (`recovery_s` list).
6. High = slow recovery.
7. Lower.
8–11. Descriptive only (not part of the verdict); v9 Auto arm `recovery_s` [4.5, 4.4, 0.5] for the runs with a drop.
12. Defined differently in the dashboard and the twin; quote which one.

#### M9. CPU: cores, % of request, % of limit, average and peak

1. *cpu_cores*: CPU in use (cores) summed over a service's pods. *cpu_pct*: average per pod as % of the CPU request (HPA's
   definition). *cpu_limit_frac*: per pod ÷ limit (feature 0). *avg/peak_cpu_pct_of_request*: mean/max of cpu_pct over all
   services and samples.
2. How busy pods are; the HPA's only signal.
3. 0.0868 cores on 1 pod, request 0.1, limit 0.5 → 86.8% of request, 0.1736 of the limit.
4. cAdvisor `container_cpu_usage_seconds_total`, rate over 1 minute.
5. `collect`; `_finalize` (`utilization`).
6. High = busy (near saturation above ~400% of request, i.e. 80% of the limit).
7. Context: too high risks latency, too low means waste.
8. HPA: `ceil(r × cpu / target)`. FlexaScale: features 0, 1, 6; guard "no scale-down at ≥ 400%"; Auto risk ≥ cpu_risk_pct.
9. The main driver of both controllers.
10. E1 Auto: average 33.5%, peak 281% of request. v9 arms `cpu_pct` mean 22.7% (Auto).
11. Default HPA runs more replicas, so lower average CPU per pod (24.3% in E1) than FlexaScale/tuned (33.5%).
12. Requests (100 m) are much lower than limits (500 m), so "% of request" can exceed 100%; a 70% target is only 14% of
    the limit. A service bottlenecked on the database shows moderate CPU while being slow.

#### M10. Memory: bytes, % of limit, average

1. *memory_bytes*: working set summed over pods; *memory_pct*: per pod ÷ memory limit (request if no limit).
2. Memory pressure.
3. 96 MiB of 256 MiB → 37.5%.
4. cAdvisor `container_memory_working_set_bytes`.
5. `collect`; `_finalize` (`avg_memory_pct`).
6. High risks out-of-memory kills.
7. Lower, with headroom.
8. Guard: no scale-down at ≥ 90%.
9. Safety only; not a policy feature in v7/v9.
10. E1: 25–26% average memory for every arm.
11. No difference.
12. Working set includes caches; the cost estimate uses memory *requests*, not limits.

#### M11. Replica counts: desired, ready, HPA desired, bounds, frozen, average, peak

1. *desired* = `spec.replicas`; *ready* = `status.readyReplicas`; *hpa_desired* = the HPA's own `status.desiredReplicas`;
   *hpa_min/hpa_max*; *frozen* = HPA carries FlexaScale's freeze annotation; *avg_total_desired* = mean over samples of
   the sum over services; *peak_total_desired*; *avg/peak_ready_replicas* (cost module).
2. Capacity requested and serving.
3. E1 Auto: average 16.6, peak 17 desired; floor = 16 services × 1.
4. Kubernetes API via discovery.
5. `_sample`, `_finalize`, `summarize_resources`.
6. High = more capacity (and cost).
7. Lower at equal performance.
8. They are the controlled quantity; feature 4 (replica fraction) and 5 (ready fraction).
9. Primary behaviour evidence.
10. v9 means: avg replicas 16.05 (Auto), peak 16.1. E1 default HPA: average 22.2, peak 27.
11. Default HPA scales up more and down later.
12. Average desired includes pods not yet ready; replica-hours uses ready.

#### M12. Scaling events, oscillations, applied scale requests, scaling delay, cooldown

1. *scaling_events*: number of desired-replica changes summed over services. *oscillations*: number of direction
   reversals (Part C.10). *applied*: FlexaScale scale requests Kubernetes accepted. *Scaling delay*: time from a FlexaScale
   decision to the new desired count (API) and to ready (pod start). *Cooldown*: guard waiting time (20 s up, 30 s down).
2. Activity and stability of control.
3. 1→2→1 = 2 events, 1 oscillation.
4. Desired series in samples; decision log.
5. `scaling_stability`; `summary.decisions.applied`; `verify_controller_modes.py` (delays).
6. Many events/oscillations = churn (pod start costs, instability).
7. Fewer oscillations (check C6); events are context.
8. Reward charges 0.25 per change; cooldowns limit frequency.
9. Stability evidence.
10. v9 means: events 3.0 (default), 0.2 (tuned), 0.4 (RL), 0.2 (Auto); oscillations 0.0/0.1/0.2/0.1. Delays: desired
    after 1.1–6.1 s, ready after 6.1–16.1 s (verification). Scale-up/down frequency is not a separate metric: derive it as
    events ÷ duration.
11. Default HPA changes most.
12. A reversal far apart in time is still counted as an oscillation (the code has no time limit).

#### M13. Replica-hours (primary resource metric)

1. Ready replicas integrated over time, in hours.
2. Resource consumption independent of prices.
3. `Σ ready × Δt / 3600`. E1 Auto: average ready 16.589 × 305.98 s / 3600 = **1.410**. Floor at 300 s: 16 × 300 / 3600 =
   **1.333**.
4. Ready counts every 5 s.
5. `summarize_resources`.
6. High = more resources.
7. Lower (check C1: interval below 0).
8. The reward's replica term is its simulated counterpart.
9. The main cost evidence.
10. v9 means: 1.512 (default), 1.366 (tuned), 1.368 (RL), 1.365 (Auto).
11. RL/Auto −7.3%/−7.7% vs default (CIs below 0); +0.3%/+0.2% vs tuned (on par).
12. Sample-based (5 s): a pod that lived 3 s may be missed. Integrates over the whole sampled window (slightly longer than
    the 300 s load).

#### M14. Allocated vs used resources and allocation efficiency

1. *Allocated vCPU-h* = Σ ready × CPU request × time; *allocated GiB-h* likewise with memory requests; *used vCPU-h* = Σ
   observed cores × time; *CPU allocation efficiency* = used ÷ allocated × 100; same for memory.
2. Waste: reserved but unused.
3. E1 Auto: allocated 0.141 vCPU-h (= 1.410 replica-h × 0.1 core), used 0.0560 → **39.7%**; memory 53.0%.
4. Requests from Deployment specs; usage from cAdvisor.
5. `summarize_resources`.
6. High efficiency = little waste (but too high = no headroom).
7. Higher, within reason.
8. —
9. Shows FlexaScale/tuned HPA do the same work on fewer replicas.
10. E1–E4: average CPU 32–40% of request for FlexaScale/tuned vs 24–28% for default HPA.
11. Default HPA least efficient.
12. Note the difference between `avg_cpu_pct_of_request` (33.46% in E1, an unweighted mean over samples and services) and
    the efficiency (39.7%, time- and replica-weighted). They answer different questions.

#### M15. Estimated cost, cost proxy, cost rate

1. *Estimated cost (USD)* = allocated vCPU-h × $0.04048 + allocated GiB-h × $0.004445 (AWS Fargate on-demand list
   prices, us-east-1). *Cost proxy* (when no prices) = vCPU-h + 0.125 × GiB-h. *Cost rate* (Overview) = $/hour of what is
   allocated now.
2. A monetary view of resource use.
3. E1 Auto: 0.141001 × 0.04048 + 0.152347 × 0.004445 = 0.005708 + 0.000677 = **$0.006385**.
4. Allocated resources.
5. `summarize_resources`; policy `cost` block.
6. High = expensive.
7. Lower.
8. —
9. Same conclusions as replica-hours (all services request the same CPU).
10. v9: $0.00685 / 0.00618 / 0.00619 / 0.00618 per run; Auto vs default −7.9% [−12.5, −3.2].
11. Follows replica-hours.
12. **An estimate, not a bill**: Minikube has no bill; real clouds price nodes, not pods; absolute values are tiny
    (fractions of a cent per run); only the percentage is meaningful.

#### M16. Decision and ownership metrics

1. Per run: *decisions.total* (services × steps), *applied*, *proposed_changes* (policy action ≠ hold index), *flexascale_owned*,
   *hpa_fallbacks* (decisions not owned by FlexaScale), *policy_modes*; Auto rule counts (`auto_counts`); per decision:
   *confidence*, *probabilities*, *policy_replicas*, *proposed_replicas*, *safety_reasons*, *hpa_recommendation*.
2. What the policy wanted vs what happened, and who owned what.
3. E1 Auto: 496 decisions (31 steps × 16), 318 proposed changes, **2 applied**. Most "proposed changes" were scale-downs of
   services already at their minimum (clamped by the bounds).
4. `decisions.jsonl`.
5. `_finalize`; `verify_controller_modes.py`.
6. —
7. —
8. They *are* the control trace.
9. Evidence for "Auto selected FlexaScale and applied scaling".
10. SLA-risk run: efficiency 462, sla_risk 34 decisions; 7 applied.
11. —
12. A proposal is not an action. Never count proposals as scaling.

#### M17. Comparison statistics: Δ%, mean, n, 95% CI, d_z, verdict checks

1. *Δ%* per pair; *mean* over pairs; *n* pairs; *95% CI* = mean ± t × s/√n; *d_z* = mean ÷ s (standardised effect size of
   paired differences); *checks C1–C7*; *verdict*.
2. Whether a difference is real or noise.
3. Auto vs default replica-hours: mean −7.748%, n = 11, CI [−12.31, −3.18]. With t(10) = 2.228: half-width 4.566 → s =
   4.566 × √11 / 2.228 = 6.80 → d_z = −7.748 / 6.80 = **−1.14** (matches the file).
4. Paired runs.
5. `lab/benchmark.py`, `scripts/analyze_v7.py` → `reports/v9/evaluation.json` (`stats`, `checks`, `verdict`).
6. A CI entirely below/above 0 = a difference at 95% confidence; |d_z| ≈ 0.2 small, 0.5 medium, ≥ 0.8 large (common
   convention).
7. Depends on the metric's direction.
8. —
9. The formal evidence.
10. Auto vs default: C1 true, **C2 false** (p95 +17.6% [−6.0, +41.2], mean above +10%), C3–C7 true → "On par /
    inconclusive". Other fields: `per_scenario_replica_hours` (e.g. flash_sale −22.9, checkout_heavy −14.5);
    `steady_app_cpu_per_request_delta_pct` = +5.99 (environment parity: Auto's shop was 6% *slower* per request in steady
    browsing, so no hidden advantage); `cpu_clock_delta_pct` not recorded on the second laptop.
11. See Section F.5.
12. 11–12 pairs is small; multiple metrics are checked, so one may pass by chance; percentages of tiny baselines can be
    large.

#### M18. Host validity metrics (`reports/host_load_by_run.csv`, `reports/v9/host_load_*.csv`)

1. *host_cores*: whole-machine CPU in use (psutil); *k8s_cores*: CPU used by the cluster's containers; *outside_cores* =
   host − k8s; *limit_cores* = idle baseline + 2.0; *battery_s*: seconds on battery; *host_affected*, *reason*; *cpu_mhz*
   (first laptop); *app_cpu_ms_per_request*: shop CPU per request (environment parity); *host_source*.
2. Whether something outside the experiment disturbed it.
3. Second-laptop baseline: idle outside 1.576 cores → limit 3.576. A run with outside 1.64 cores passes.
4. psutil samples every 5 s; Prometheus; battery state.
5. `scripts/check_host_load.py`, `scripts/measure_host_baseline.py`.
6. High outside cores = disturbed.
7. Lower.
8. —
9. Validity of every pair.
10. 7 of 53 v9 runs were host-affected (all FlexaScale/Auto) and excluded; early runs on battery are flagged.
11. —
12. Only CPU and power are checked; memory pressure was found later (late reruns).

#### M19. Training metrics (Stable-Baselines3 logs; v4 example from `logs/train_v4_lr1e-4_ent0.01_s3.log`)

| Metric | Meaning | Example value | Reading |
|---|---|---|---|
| `ep_rew_mean` | Mean episode reward over recent episodes | −20.8 → −12 | Rising = learning |
| `ep_len_mean` | Mean episode length (steps) | 30 | Fixed by the simulator |
| `fps` | Environment steps per second | 1685 → 30 | Speed (falls when evaluation runs) |
| `total_timesteps`, `iterations`, `n_updates` | Progress counters | 1,001,472; 489; 4,880 | — |
| `approx_kl` | Approximate KL divergence between old and new policy per update | 0.008–0.017 | Size of the policy change; large = unstable |
| `clip_fraction` | Share of samples whose ratio was clipped | 0.026–0.109 | High = updates hitting the limit |
| `clip_range` | ε | 0.2 | Setting |
| `entropy_loss` | Negative entropy | −4.39 → −3.61 | Less negative = less random (multi-head policy, so values below −1.6) |
| `explained_variance` | 1 − Var(G − V)/Var(G): how well the critic predicts returns | 0.03 → 0.49 | 1 = perfect, 0 = useless |
| `value_loss` | Critic's mean squared error | 57 → 31 | Falling = critic learning |
| `policy_gradient_loss` | The clipped surrogate (negated) | −0.004 | Small; not a quality measure |
| `loss` | Total loss | 27 → 12 | Mostly the value term |
| `learning_rate` | Step size | 1e-4 | Setting |

For v7/v9 the SB3 console logs were not kept on this laptop (v9 trained on the second laptop); their training is
summarised by **validation reward** per checkpoint (`reports/v9/training_v7.json`, model cards). Warm-start quality is
reported as **agreement** (share of held-out decisions equal to the teacher's), **recall per action**, and **value MSE**
vs the return variance.

#### M20. Reward, episode return and reward components (simulated)

1. *Step reward* (Section 7.6 of the explanation); *episode reward* = sum over the episode's steps; *validation reward* =
   mean episode reward over 40 validation workloads; components: `replicas_above_min`, `p95_inflation`, `slo_fraction`,
   `failure_pct`, `scaling_events`.
2. How good a controller is under the training objective.
3. Example step: −0.1 × (3 + 0.25) = −0.325.
4. Twin.
5. `twin_env.reward_v7`, `episode_reward`, `train_v7.run_set/agg`.
6. Closer to 0 = better (it is a penalty).
7. Higher.
8. It is what PPO maximised.
9. Selection and the gate.
10. v9 runs' best validation: −2.466 (focal_bc_s2), −2.922 (no graph), −2.990 (s1), −3.299 (old reward); rule −2.99; gate
    v9 −2.47 vs v7 −2.91.
11. In T1 tuned HPA −1.196 vs v9 −1.255; in T2 v9 −2.548 vs tuned −3.060.
12. Simulated; the seed-to-seed spread (0.52) is as large as design differences; selection on the same set flatters the
    winner.

#### M21. Twin fidelity and test-set columns

* *Twin check* (`reports/v9/twin_check.md`): live vs twin replica-hours, p95 and mean latency per HPA target; mean absolute
  error v9 twin 2.0% / 8.9% / 4.4%; v7 twin on the second laptop 1.9% / 20.5% / 17.7%.
* *T1–T3 tables* (`reports/v9/ablation.md`): columns `reward`, `replica-h`, `p95 ms`, `mean ms`, `SLO violation s`,
  `events`, `osc` per controller (all simulated).
* *Graph ablation*: Δ reward / replica-h / p95 / SLO with 95% CIs, graph − no graph, paired by episode.
* *v9 vs v7* (`reports/v9/v9_vs_v7.md`): every reward interval includes 0 on both twins → the two models tie on held-out
  tests.

#### M22. Older simulation metrics (`reports/simulation_evaluation_v4/v5/v6.md`)

Columns: *reward/step*, *SLO violation rate* (fraction of service-steps above the service's SLO), *avg replicas*, *avg
CPU %*, *replica changes/step*, each ± 95% half-width over 300 paired episodes; paired differences and *episodes v5
better*. Example (v5): reward −0.274 vs HPA-like rule −0.338 (v5 better by 0.064 ± 0.031) but worse than a tuned rule
(−0.048 ± 0.013), with 0.44 more replicas. **Simulated**, Alibaba-driven; did not carry over live.

#### M23. GNN quantities

| Quantity | Value | Meaning |
|---|---|---|
| Nodes | 16 real of 20 slots | Services |
| Edges | 25 directed | Calls |
| Node features | 10 | Section 8.1 of the explanation |
| Adjacency | 20 × 20 binary | Caller rows, callee columns |
| Degrees | e.g. api-gateway out-degree 9; order-service out-degree 7, in-degree 1; catalog-service in-degree 6 | Number of callees / callers |
| Embedding size | 64 per node; readout 128 | Learned summary |
| Rounds | 2 | Receptive field 2 hops |
| Parameters | 42,566 | Section 8.7 |

"Dependency information" in this project = the adjacency matrix plus message passing; no traffic-weighted edges are used
for the shop.

#### M24. Alibaba dataset columns (`data/processed/alibaba_service_state*.csv`)

`timestamp` (ms from trace start), `service_id` (hashed msname), `cpu_utilization` (%), `memory_utilization` (%),
`replica_count`, `request_rate`, `latency_ms` are **trace-derived**. `source`, `submit_time`, `start_time`,
`finish_time`, `completion_time`, `wait_time`, `makespan`, `cpu_memory_ratio`, `cpu_capacity`, `gpu_count`,
`gpu_utilization`, `gpu_memory`, `jct`, `acceptance_ratio`, `successful_requests`, `failed_requests`, `error_rate`,
`success_rate` are **filled by rule** for schema compatibility (explanation Section 5.2). Do not present them as
measurements.

### F.3 Every results file, its columns and what it concludes

| File | Purpose | Columns / content | Conclusion |
|---|---|---|---|
| `results/RESULTS.md` | Curated results with charts and evidence | Narrative + tables | The summary you present |
| `results/data/selected_runs.csv` | One row per selected run (E1–E4 arms + verification runs) | `experiment, experiment_title, arm, run_id, block, scenario, controller, users, spawn_rate, duration_s, actual_duration_s, state, initial_replicas, hpa_bounds, hpa_config, flexascale_config, throughput_rps, total_requests, p50_ms, p90_ms, p95_ms, p99_ms, mean_ms, error_rate_pct, avg_cpu_pct_of_request, peak_cpu_pct_of_request, avg_memory_pct, avg_replicas, peak_replicas, replica_hours, estimated_cost_usd, cpu_allocation_efficiency_pct, e2e_slo_violation_s, e2e_slo_violation_fraction, sla_status, scaling_events, cleanup_safe, raw` (all defined in F.2) | Per-run evidence for E1–E4 and verification |
| `results/data/comparisons.csv/.json` | Pooled pre-registered comparisons | `study, comparison, pairs, verdict, replica_hours_mean, cost_mean, p95_ms_mean, failure_pct_mean, throughput_mean, replica_hours_ci95, p95_ms_ci95, source` (means are Δ%; failure in pp) | Savings vs default; parity vs tuned |
| `results/data/v9_auto_vs_default_pairs.csv` | Every pair behind Auto vs default | `block, scenario, candidate, reference, replica_hours, cost, p95_ms, p99_ms, failure_pct, throughput` (Δ% per pair; failure Δ in pp) | Where the saving comes from (flash sale, checkout heavy) |
| `results/charts/*.svg`, `screenshots/*.png` | Charts and dashboard captures | — | Visual evidence |
| `results/verification/README.md`, `*.json` | End-to-end verification | JSON keys: `run` (id, state, controller, model + sha256, cleanup, operator_failure, workload, replicas, resources), `totals`, `operator_events`, `lab_events`, `per_service`, `exclusivity_violations`, `faults`, `snapshots`, `request` | All three modes and fallbacks work |
| `reports/experiments/<id>/run.json` | Everything about one run | `id, request, state, timestamps, events, samples, summary, cleanup, model, initial/start_replicas, slo, auto_state, auto_counts, policy` | Raw truth |
| `…/telemetry.csv` | One row per service per 5 s sample | `t, elapsed, users, rps, fail_rps, p50_ms, p90_ms, p95_ms, p99_ms, e2e_slo_violation, service, desired, ready, hpa_desired, hpa_min, hpa_max, frozen, cpu_pct, memory_pct, cpu_cores, memory_bytes, request_rate, latency_ms, latency_p50/p90/p95/p99_ms, error_rate, stale` | Timeline data |
| `…/decisions.jsonl` | One record per service per operator step, plus events | `type, ts, step, app, mode, service, features, missing, stale, policy{mode, action, action_label, delta, confidence, probabilities, window, clipped}, current_replicas, ready_replicas, hpa, hpa_recommendation, policy_replicas, auto{owner, rule, reason, candidate, hpa_recommendation, flexascale_proposal, streak, inputs}, controller, proposed_replicas, safety_reasons, applied, apply_error, hpa_note, policy_input` | Explainability |
| `…/locust_stats.csv` | Whole-run Locust stats | `Type, Name, Request Count, Failure Count, Median/Average/Min/Max Response Time, Average Content Size, Requests/s, Failures/s, 50%…100%` | End-to-end outcome |
| `…/locust_stats_history.csv` | Periodic Locust rows | `Timestamp, User Count, Type, Name, Requests/s, Failures/s, percentiles, Total Request/Failure Count, Total Median/Average/Min/Max Response Time, Total Average Content Size` | Window percentiles for the SLO |
| `…/locust_failures.csv`, `locust_exceptions.csv` | Errors by type | `Method, Name, Error, Occurrences, First/Last Seen` | Why requests failed (e.g. 400 empty cart, 502 under contention) |
| `reports/live_benchmark_summary.csv` | One row per recorded run (289) | `run, app, controller, model, scenario, users, duration_s, state, complete, preliminary, requests, requests_seen_in_samples, throughput_rps, failure_pct, p50_ms, p95_ms, p99_ms, e2e_slo_violation_s, avg_replicas, peak_replicas, replica_hours, alloc_vcpu_h, used_vcpu_h, cpu_alloc_eff_pct, estimated_cost, cost_proxy, scaling_events, oscillations, applied_scale_requests, cleanup_safe, settled_start` | Input to the live report |
| `reports/live_benchmark_report.md` | Pooled pairs by model/mode vs default HPA | Summary table + block studies | History v3–v9 |
| `reports/v9/evaluation.md/.json` | Pre-registered v9 verdicts | `blocks, excluded, comparisons{pairs, stats, verdict, checks, per_scenario_replica_hours, …}, arms` | Final verdicts |
| `reports/v9/calibration.md/.json` | Tuned-HPA calibration | Target, valid runs, p95, mean, failures, replica-h, throughput, meets rule | 350% selected |
| `reports/v9/twin_check.md`, `ablation.md`, `v9_vs_v7.md`, `evaluation_sensitivity.md`, `gate.json`, `arms.json`, `*_plan*.json`, `host_*` | Twin fidelity, test sets, ablation, robustness, gate, design, validity | See M18–M21 | Supporting evidence |
| `reports/v7/evaluation.md`, `replication.md`, `calibration.md` | First-laptop studies | Same structure | Withdrawn batch (confound) and on-par replication |
| `reports/simulation_evaluation*.md/json` | v2–v6 simulated tests | See M22 | Simulation gains that did not transfer |
| `reports/data_quality_report.md/json` | Dataset checks | Shape, units, splits, distributions | Data provenance |
| `reports/shopping_benchmark_*`, `reports/locust_hpa_phase_*`, `reports/locust_rl_phase_*` | Early 7-service, 60 s benchmark | Telemetry and Locust files | **Withdrawn**: used an untrained network head and mis-scaled data |
| `reports/benchmark_report.md`, `benchmark_summary.json` | Early simulated benchmark (3 episodes) | Identical numbers for HPA and RL, 20 fallbacks per episode | **Superseded**: every decision fell back to the heuristic, so it measured no difference |
| `reports/experiments_invalid/README.md` | Every excluded run and why | — | Transparency |

### F.4 How the metrics work together

A scaling decision needs several signals at once:

* **RPS up, CPU up, latency up** → genuine overload: add replicas (both HPA and FlexaScale agree).
* **CPU up, RPS flat, latency flat** → a brief CPU blip (e.g. checkout-heavy E3/E4): adding replicas wastes capacity;
  default HPA did this, FlexaScale and tuned HPA did not.
* **Latency up, CPU moderate** → a non-CPU bottleneck (order-service waiting on the database): replicas may help a little
  or not at all; a CPU-only controller under-reacts, a latency-aware one would react (future work).
* **RPS falls** → release capacity soon (FlexaScale's 30 s cooldown vs HPA's 300 s window): the source of the flash-sale
  saving.
* **Ready < desired** → pods are starting: wait (readiness guard) rather than add more.

**Why optimising one metric fails.** Minimise replicas only → the policy holds 1 replica during a spike (p95 explodes).
Minimise latency only → scale everything up (the v1–v3 failure: +77% replica-hours). Minimise churn only → never act.
The reward combines them with explicit weights, and the verdict requires cost **and** latency **and** failures.

**Over-provisioning** = more replicas than the load needs (default HPA in E1: 27 replicas, kept 5 minutes). **Under-
provisioning** = fewer than needed (FlexaScale at 40 users on the Fedora laptop: p95 2–6 s). **Resource efficiency** =
work done per allocated resource (M14). **Cost estimation** = allocated resources × list prices (M15).

### F.5 HPA vs FlexaScale vs Auto — the honest comparison

| Situation | Who did better | Why | Evidence |
|---|---|---|---|
| Flash sale vs **default** HPA | FlexaScale/Auto (fewer replicas, lower p95 in E1/E2) | Default HPA reacted late and held capacity for 300 s | E1, E2 (single pairs) |
| Checkout heavy vs default HPA | FlexaScale/Auto on cost; HPA slightly on p95 (+6%) | Default HPA scaled for brief CPU rises | E3, E4 |
| Gradual ramp, traffic drop vs default HPA | Default HPA on latency (Auto p95 +30–65%) | Lean replicas meet bursts before scale-ups | v9 pairs |
| Pooled vs default HPA | FlexaScale on cost (−7.3/−7.7%), not proven on latency | Above | v9 evaluation |
| vs **tuned** HPA | Neither (on par) | A higher target + 60 s window removes the same waste | v7 replication, v9 |
| Non-CPU bottleneck at 40 users (Fedora) | Default HPA reacted, FlexaScale did not | Its 70%-of-request target is only 14% of the limit; policies read CPU vs the limit | Verification runs |
| Safety under failures | FlexaScale/Auto hand back correctly | Lease, freeze, watchdog | Verification |
| Explainability | FlexaScale/Auto | Per-decision reasons and rules | Decision logs |

### F.6 Misleading interpretations to avoid

* Counting **proposals** (green dashed line, "would propose") as scaling. Only ◆ + desired change are actions.
* Presenting **simulated** rewards as live performance.
* Quoting **E1** (one pair) as the overall result; the pooled verdict is "on par / inconclusive".
* Comparing with the **default** HPA only; the fair baseline is the tuned HPA.
* Reading **cost in dollars** as real money saved.
* Treating **"≥ 10000 ms"** as a measured value; it is a lower bound.
* Ignoring that the **v6 −3.9%** and the first **v7 "beats on performance"** were affected by a power-profile confound.
* Calling the graph "proven beneficial"; the ablation found no measurable benefit.

---

## Part G — Research papers and novelty

### G.1 What the repository contains (and does not)

**There are no research-paper PDFs in the repository.** The only literature material is the team's own Phase 2
documents in `PPT AND REPORT/`: *Literature Review A1 – Phase 2.pdf* (a preliminary survey of five papers with a
comparison table, research gap and novelty) and *Design and Solutions – A1 phase 2.pdf* (architecture, methodology and the
same five references). The details below for those five papers come **only** from those documents. The final project
report reviews seven more papers; those paragraphs were written from general knowledge of the papers, not from files in
the repository, so **verify every number and author list against the papers themselves before the viva**.

### G.2 The five papers in the team's literature review

| # | Paper (as listed by the team) | Year | Key contribution (team's words) | Methodology | Dataset / evaluation | Limitation / gap (team's words) |
|---|---|---|---|---|---|---|
| 1 | Santos et al., *Gwydion: Efficient Auto-Scaling for Complex Containerized Applications in Kubernetes through Reinforcement Learning*, J. Netw. Comput. Appl. 234, 104067 | 2025 | RL-based Kubernetes autoscaling that considers microservice dependencies; cost- and latency-aware rewards | Deep RL considering microservice dependencies | Redis Cluster and Online Boutique on Kubernetes | Mainly horizontal scaling and predefined reward strategies; limited adaptive multi-objective optimisation |
| 2 | Ahmad et al., *Towards Resource-Efficient Reactive and Proactive Auto-Scaling for Microservice Architectures*, J. Syst. Softw. 225, 112390 | 2025 | Smart HPA and ProSmart HPA: reactive and proactive scaling with ML workload prediction | Resource-efficient HPA with ML prediction | Real Kubernetes microservice benchmark | No reinforcement learning for continuously learned policies |
| 3 | Pandey, *Reinforcement Learning-Based Autoscaling for Cost and Performance Optimization in Kubernetes Clusters* | 2025 | Multidimensional RL autoscaler, horizontal + vertical, jointly optimising latency, cost and SLA | PPO and DDPG | Spark TPC-DS on an EKS cluster | Extensive training; cost–latency focus without modelling service dependencies |
| 4 | Shi et al., *AdaptScale: An Adaptive Data Scaling Controller for Improving Multiple Performance Requirements in Clouds*, FGCS 105, 814–823 | 2020 | Adaptive workload prediction + greedy heuristic for multiple SLAs with minimal resources | Greedy heuristic with workload prediction | Simulation platform | Cloud *data* scaling, not Kubernetes microservice autoscaling |
| 5 | El Haj Ahmed et al., *KubCG: A Dynamic Kubernetes Scheduler for Heterogeneous Clusters*, Softw. Pract. Exp. 51(2), 213–234 | 2021 | Dynamic scheduler using historical execution information for CPU–GPU clusters | Dynamic scheduling from execution history | Heterogeneous Kubernetes cluster | Scheduling efficiency, not runtime autoscaling |

**A detail to fix in your own documents.** In both Phase 2 PDFs the reference list titles paper 4 "*FlexaScale:* An
Adaptive Data Scaling Controller…", while the literature table calls it "*AdaptScale*". The final report uses
"AdaptScale". Check the actual paper's title before the viva; an examiner who notices will ask.

### G.3 What FlexaScale adopted, modified or did differently

| Idea | Source in the literature | What FlexaScale did |
|---|---|---|
| Dependency information in an RL autoscaler | Gwydion [1] | Adopted and **modified**: a GNN with directed caller/callee messages over the real call graph, focal per-service decisions with per-service rewards |
| A tuned rule can be strong | Smart HPA [2] (and the team's own finding) | Made it part of the **evaluation**: a calibrated tuned HPA is the primary baseline |
| PPO for autoscaling | Pandey [3] | Adopted PPO (Stable-Baselines3); addressed training cost with a fitted twin and imitation warm start |
| Several performance requirements in one objective | AdaptScale [4] | One reward with explicit weights for replicas, latency inflation, SLO, failures and churn |
| Use measurements of the actual system | KubCG [5] | The application twin is fitted to measured CPU per request and pod start-up times |

### G.4 What is genuinely different, and what is not

**Defensible claims** (each backed by code and evidence):

1. Per-service, explainable arbitration between a learned policy and the native HPA (Auto mode), with exclusive
   ownership enforced by a Lease and an HPA freeze, and verified fallback in every failure mode tested.
2. A fair, pre-registered live evaluation against both the default and a calibrated HPA, including negative results,
   withdrawn confounded batches and an ablation of the graph.
3. Training in an application twin fitted to the live system, checked for fidelity before use.

**Claims you must not make:** that FlexaScale beats a tuned HPA; that the GNN is proven to help; that the method is the
first RL autoscaler or the first dependency-aware one (Gwydion and others predate it); that the cost numbers are real
savings.

**Phase 2 design elements not implemented:** adaptive reward weighting by traffic phase; online PPO updates on the live
cluster; PyTorch Geometric in the final model; a three-node cloud cluster. The confidence-proxy fallback was implemented
(Auto rule 2 and the non-Auto confidence gate) but set to 0 in the shop's policy.

---

## Part H — Mistakes, bugs, debugging and troubleshooting

### H.1 Real problems met in this project (all documented in the repository)

| # | Problem | How it showed up | Fix | Source |
|---|---|---|---|---|
| 1 | Alibaba CPU/memory stored as fractions, consumers expected percent | v1 trained on near-zero CPU | Rescaled ×100 with provenance; builder fixed | `reports/data_quality_report.md` |
| 2 | Early live benchmark used the GNN's `node_policy_head`, which PPO never trained | "FlexaScale" numbers did not come from a trained policy | Report withdrawn; runtime only uses trained parameters | `reports/shopping_benchmark_report.md` |
| 3 | Pods scraped by two jobs counted twice | Request rates 2× too high on the first laptop (v7 twin fitted on doubled rates) | Sum per (pod, job), max over jobs | `docs/POLICY_V9.md` §8 |
| 4 | cAdvisor without `container` label (Docker on cgroup v2) | CPU missing for every service → FlexaScale would hold everything | Fall back to pod-level series | `workload_metrics.py` docstring |
| 5 | Zero traffic reported as missing | Idle services looked broken | `up == 1` with no series → rate 0, `no_traffic` | same |
| 6 | `localhost` cost 2 s per query on Windows | Slow sampling | Use 127.0.0.1 (IPv4) | `docs/POLICY_V9.md` §1.1 |
| 7 | Each downstream call created its own HTTP client; order history returned every order (43k) | order-service OOM-killed in both arms; 36 runs invalidated | Shared client; history limited to 20 | `reports/final_readiness_report.md` defects 13–14 |
| 8 | Laptop power profile `balanced` | Shop ran faster whenever FlexaScale's control kept the host busy → false "beats" | Replication under `performance` profile; batch withdrawn | `docs/V7_REPORT.md` §4.1 |
| 9 | Runs on battery, Modern Standby, lid closed, laptop suspend | Disturbed or interrupted runs | Validity rule; reruns; sleep inhibition | `reports/experiments_invalid/README.md` |
| 10 | Operator killed → HPAs stayed frozen | No autoscaling until manual restore | Lab watchdog | `lab/experiments.py` |
| 11 | Two Helm releases selected each other's operator pods | Lifecycle test read the wrong pod | Release-specific selector (chart 0.5.1) | `helm/flexascale/templates/operator-deployment.yaml` |
| 12 | `kubectl` killed with no message | Empty error in logs | Report the exit code | `k8s/kube.py` |
| 13 | PPO from scratch learned "scale everything up" | v1–v3 over-provisioning (+77.5% replica-hours) | Unit-free features, bounded penalties, imitation warm start | `docs/FINAL_PROJECT_SUMMARY.md` §6 |
| 14 | Uncapped latency inflation in the reward | Rare overloads dominated gradients | Cap at 4 | `twin_env.RewardConfig` |
| 15 | Teacher rule almost never scales up (17 of 24,647 labels) | Imitation never learned scale-ups (`models/flexascale_v7_bc_imbalanced`) | Class weights + relabelled CPU augmentation | `rl/imitation_v7.py` |
| 16 | Twin queues unbounded | Unrealistic overloads (`models/flexascale_v7_unbounded_queue`) | Closed-loop bound by waiting users | `simulator/twin.py` |
| 17 | `kubectl scale` to the minimum undone by HPA's 300 s memory | Runs did not start comparably | Freeze HPAs at minimum, wait out the window, restore, verify | `Experiment._reset_replicas` |
| 18 | Confidence fallback with threshold 0.7 in early simulation | Every decision fell back to the heuristic; identical results | Thresholds revisited; benchmark superseded | `reports/benchmark_summary.json` |

### H.2 Troubleshooting (symptom → cause → what to do)

| Symptom | Likely cause | Action |
|---|---|---|
| Dashboard chip "Prometheus" red | Port-forward died | `./fsctl start` (restarts port-forwards) |
| Alert "HPA left frozen" | An operator stopped without hand-back | `./fsctl stop` (restores every HPA) |
| "Lease held outside an experiment" | A previous operator still holds or recently held it | Wait 30 s for expiry, or `./fsctl stop --force-release-lease` |
| Start refused | Another run, Locust or operator still active, or a Lease held | Stop it; check `./fsctl status` |
| "NO MODEL (CPU heuristic)" | Model file missing or incompatible | Live mode is refused; check `model_path` and the Models page |
| Telemetry "stale" or "missing" | Prometheus targets down, pods not scraped | Check targets; FlexaScale hands those services to HPA automatically |
| FlexaScale never scales on the Fedora laptop | v9 is fitted to the other laptop | Choose policy v7 |
| p95 shows "≥ 10000" | Percentile beyond the largest bucket | A lower bound, not a measurement |
| Runs not comparable on the Comparison page | Different users/duration, unsettled start, incomplete | Rerun with Comparable start |

### H.3 Common conceptual mistakes

* Confusing CPU % of **request** (HPA's signal, can exceed 100%) with CPU % of **limit** (FlexaScale's feature 0).
* Thinking the GNN outputs replica counts (it outputs embeddings; the actor outputs probabilities; the operator turns an
  action into a count; safety may change it).
* Thinking FlexaScale learns live (it does not).
* Thinking Auto mixes the two controllers' numbers (it chooses **one owner** per service per step).
* Thinking the HPA is switched off under FlexaScale (it is frozen, still running, and restored on hand-back).

---

## Part I — Viva questions and answers

### I.1 Basic

1. **What problem does FlexaScale solve?** Kubernetes' HPA scales each service on its own CPU with one fixed target, reacts
   late and keeps spike capacity for five minutes. FlexaScale uses a learned, dependency-aware policy with a safety layer,
   and keeps the HPA as a fallback.
2. **What is a microservice?** A small program that does one job and talks to others over the network.
3. **What is a pod, a Deployment, a replica?** The running unit; the instruction to keep N identical pods; one of those N.
4. **Desired vs ready replicas?** Asked for (`spec.replicas`) vs actually serving (`status.readyReplicas`); ready lags by
   ~10–15 s after a scale-up.
5. **How does the HPA decide?** `ceil(r × CPU / target)`, ±10% tolerance, scale-down uses the highest recommendation of the
   last 300 s.
6. **What is reinforcement learning?** Learning decisions by trial and error to maximise a reward.
7. **What are state, action and reward here?** 10 features per service plus the call graph; replica change −1…+3; a
   penalty for replicas, latency inflation, SLO violation, failures and churn.
8. **What is a GNN?** A network that passes information along a graph's edges.
9. **What is PPO?** An RL algorithm that improves the policy in small, clipped steps using an actor and a critic.
10. **What is Prometheus?** A time-series database that scrapes metrics; FlexaScale queries it with PromQL.
11. **What is Locust?** A load generator that simulates users.
12. **What is p95?** The time within which 95% of requests finished.
13. **What is your SLO?** End-to-end p95 ≤ 1000 ms per ~10 s window.
14. **What are replica-hours?** Ready replicas × time in hours; our main resource measure.
15. **What dataset did you use?** Alibaba cluster-trace-microservices-v2021 (30-minute shard) for v1–v6; the live shop's
    own measurements for the twin used by v7/v9.
16. **How many services and edges?** 16 services, 25 edges.
17. **What is the observe mode?** FlexaScale logs decisions without changing the cluster; the default.
18. **What are the three modes?** Native HPA (FlexaScale may shadow), FlexaScale (owns every service), Auto (per-service
    owner).
19. **How often does FlexaScale decide?** Every 10 seconds.
20. **Where is the model?** `models/flexascale_v9/best_model/best_model.zip` (SHA-256 `2f95764b…`), 42,566 parameters.
21. **What language and frameworks?** Python, PyTorch, Stable-Baselines3, Gymnasium, FastAPI; React/TypeScript dashboard;
    Kubernetes, Helm, Prometheus, Grafana, Locust.
22. **How do you start it?** `./fsctl start`, dashboard at `http://127.0.0.1:8090/`; `./fsctl stop`.
23. **How many tests?** 373, all passing.

### I.2 Intermediate

24. **Why CPU relative to the limit, not the request?** Pods saturate (are throttled) at the limit; with a 0.1-core
    request and a 0.5-core limit, "% of request" can be 400% and still be safe.
25. **Why latency relative to each service's own minimum?** Services have different normal latencies (login with bcrypt
    is slow by design); one absolute SLO for all would be wrong.
26. **Why unit-free features?** The policy is trained in a simulator and used live; ratios mean the same in both and across
    services.
27. **What exactly enters the GNN?** 20 × 10 features, a 20 × 20 adjacency matrix, a 20-mask, and a 20-number one-hot of
    the focal service: 660 numbers.
28. **What exactly comes out?** 128 numbers: the focal service's embedding after two rounds and the mean embedding of all
    services.
29. **How are callers and callees treated differently?** Separate weight matrices `W_callee` and `W_caller`; means over
    `A·H` and `Aᵀ·H`.
30. **Why two rounds?** A two-hop receptive field reaches the checkout fan-out (gateway → order → payment) while staying
    small and trainable.
31. **Why mean aggregation?** So high-degree nodes (api-gateway, 9 callees) are not dominated by the number of neighbours.
32. **What does "focal" mean?** Each service's decision is a separate row with a one-hot marking it, so each decision gets
    its own reward (credit assignment).
33. **How is the action turned into replicas?** Index → delta via the model card's `(−1, 0, +1, +2, +3)`; clipped to
    [−1, +3] and bounds 1–10; then the guards.
34. **What is confidence?** The probability of the chosen action. Thresholds are 0 in the shop's policy.
35. **What guards exist?** Bounds, step limits, budget 48, readiness, 20/30 s cooldowns, no scale-down at ≥ 400% CPU, ≥ 90%
    memory or above SLO, stale telemetry → HPA.
36. **How do you prevent FlexaScale and HPA from fighting?** Freeze the HPA (min = max = FlexaScale's count) before
    scaling; restore from annotations on hand-back; one Lease per application.
37. **What does the Lease protect against?** Two FlexaScale instances controlling the same application.
38. **What happens if the operator crashes?** The lab watchdog restores all HPAs (verified: about 1.4 s after SIGKILL); in
    the Helm install the hand-back hook covers upgrades and uninstalls.
39. **What if Prometheus goes down?** All services' telemetry becomes stale → Auto rule 1 / guard 0 → HPA in the same step
    (verified).
40. **What are the four Auto rules?** Controller health → HPA now; confidence → HPA; SLA risk with HPA wanting more → HPA
    now; otherwise efficiency → FlexaScale after 2 steps.
41. **Why is switching to FlexaScale slower than to HPA?** Handing to HPA is the safe direction; delays there could harm
    users. Hysteresis avoids flapping.
42. **What is the application twin?** A simulator fitted to the shop's measurements: CPU per request, limits, queueing,
    call graph, pod start, delayed metrics.
43. **How accurate is it?** v9 twin vs live: 2.0% replica-hours, 8.9% p95, 4.4% mean latency error.
44. **Why imitation before PPO?** PPO from scratch learned "scale everything up" or could not match a simple rule; starting
    from the rule gives a good policy that PPO can refine.
45. **What hyperparameters?** n_steps 64 × 80 agents, batch 512, 10 epochs, lr 1e-4, clip 0.1, target KL 0.02, γ 0.97, λ
    0.95, entropy 0.01, value coef 0.5, grad norm 0.5; 2M agent-steps per run.
46. **How was the model selected?** Best validation reward over 40 workloads (focal_bc_s2, −2.466), then a gate against v7.
47. **What is a tuned HPA?** HPA with the CPU target and window chosen by a rule fixed in advance: highest target whose
    p95, mean latency and failures stay within 10% of the 70% target; 350%/60 s on the second laptop.
48. **Why compare against a tuned HPA?** The default HPA over-provisions this lightly loaded shop and is easy to beat;
    the tuned one is the fair baseline.
49. **What does "pre-registered" mean?** The rules were written down before the first run, with a time-stamped record.
50. **What is a 95% CI here?** mean Δ ± t × s/√n over paired blocks; if it includes 0, no proven difference.

### I.3 Advanced

51. **Write the PPO clipped objective and explain the min.** `E[min(ρÂ, clip(ρ, 1−ε, 1+ε)Â)]`; the min takes the
    pessimistic value, so the gradient stops once the ratio leaves [1−ε, 1+ε] in the improving direction.
52. **What is GAE and why λ = 0.95?** An exponentially weighted sum of TD errors; λ balances bias (low λ) and variance
    (high λ); 0.95 is a standard, stable choice.
53. **Why γ = 0.97?** Effective horizon ~33 steps (~5.5 min): long enough to see pod start-up and cooldown effects, short
    enough for stable value estimates in 30–60-step episodes.
54. **How is the critic used?** Only in training: it gives V(s) for advantages; it is fitted with a 0.5-weighted MSE.
55. **Why per-service rewards, and do they sum to the global reward?** Each service pays its own replicas and churn plus a
    share of the latency penalty proportional to traffic share × own excess latency; the shares sum to 1, so the rewards
    sum to the global reward.
56. **What does LayerNorm do in your GNN and why the residual?** Keeps embeddings in a stable range; the residual keeps a
    node's own information and eases gradient flow.
57. **How many parameters and where?** 25,664 in the extractor, 16,512 in the two 64-unit hidden layers, 325 action head,
    65 value head = 42,566.
58. **How do you handle variable numbers of services?** 20 padded slots with a mask; padded embeddings stay 0 and are
    excluded from the mean; more than 20 services are refused.
59. **What did the graph ablation show?** Reward differences graph − no graph had CIs including 0 on T1, T2 and T3: no
    measurable benefit on this shop.
60. **Why might the graph not help here?** Load on each service is visible in its own features soon enough at 25 users;
    most services sit at the floor; the twin's 9% p95 error is as large as the differences the graph could exploit.
61. **Explain the histogram percentile interpolation and its error.** Linear inside the bucket reaching rank q × total;
    the error can be up to the bucket width (e.g. 100–250 ms).
62. **What is the difference between e2e p95 and per-service p95?** E2E from Locust, actual times; per service from
    histograms, interpolated, 1-minute window.
63. **Why is cost an estimate?** Allocated resources × public list prices; Minikube has no bill; clouds bill nodes.
64. **Explain d_z for Auto vs default replica-hours.** Mean −7.75%, SD of paired differences ≈ 6.8 → d_z ≈ −1.14, a large
    standardised effect.
65. **Why is the verdict "on par" despite a CI below zero for cost?** Check C2 failed: p95 mean +17.6% with a CI that
    includes large increases; "beats on cost" requires latency not to be worse.
66. **What is check C7?** Replica-hours lower in at least 4 of 6 scenarios, so one scenario cannot carry the result.
67. **What was the power-profile confound?** Under `balanced`, the CPU clock followed host load; FlexaScale's live control
    added ~0.55 cores of host activity, so the shop ran faster in FlexaScale arms even when decisions were identical. A
    replication under `performance` removed it.
68. **How did you check environment parity in v9?** `steady_app_cpu_per_request_delta_pct`: Auto's shop used 6% *more*
    CPU per request in steady browsing, so no hidden speed advantage.
69. **Why did v9 hold every service at one replica on the Fedora laptop?** Its behaviour was learned on the second
    laptop's twin, starting from a teacher rule that scales up at about 60% of the CPU limit; on the Fedora laptop at 40 users CPU per pod stayed at 30–50% of the
    limit while order-service was database-bound.
70. **Why didn't Auto hand those services to HPA?** Its CPU risk level (400% of request = 80% of the limit) was not reached
    and the shop has no per-service latency SLO; with a 60% threshold (controlled variant) it did.
71. **Is the Lease safe against two operators starting at the same moment?** Yes: `kubectl replace` with the
    `resourceVersion` fails for the slower one (optimistic concurrency).
72. **What if the operator dies while holding a frozen HPA and no lab is running (in-cluster)?** The Lease expires after 30
    s, but HPAs stay frozen until an operator or `./fsctl stop` restores them. The Helm hook covers upgrades and
    uninstalls. Kubernetes restarts a crashed operator pod; by reading the code, the new operator takes the expired Lease
    and, for every service it hands to HPA, `ensure_hpa_active` restores a frozen HPA. This restart path was **not**
    tested live, and a standalone in-cluster watchdog is not implemented; say so as a limitation.
73. **What is the difference between `policy_replicas` and `proposed_replicas`?** The policy's clipped proposal before
    safety vs the approved count after safety (and ownership).
74. **How is the decision for all 16 services computed efficiently?** One batched forward pass of 16 rows.
75. **Could FlexaScale manage an app without a configured topology?** Yes: edges are inferred from the gateway's forward
    counters (bookstore); without any traffic metrics only a weak name-order heuristic remains.

### I.4 Difficult examiner questions

76. **"So your RL system is no better than a tuned HPA. What is the contribution?"** A safe, explainable framework that lets
    a learned policy share control with the HPA, a fair evaluation method, and the finding that, at this scale, a
    calibrated rule matches the learned policy. Negative results are results; the framework is ready for settings where
    learned policies may help (larger, more dependent workloads).
77. **"Your best result is one flash-sale pair. Isn't that cherry-picking?"** The pooled pre-registered verdict is reported
    first; E1–E4 were selected by a stated rule to illustrate the mechanism, and the limitation (single pairs) is written
    next to them.
78. **"Why not compare with other RL autoscalers?"** Their code and setups were not available for our shop and laptop;
    the HPA (default and tuned) is the standard baseline; this is a limitation.
79. **"25 users is tiny."** Yes; the single-node cluster limited load. At 25 users most services stay at one replica,
    which bounds any saving; heavier, multi-node experiments are future work.
80. **"Simulation results are meaningless."** They are used for training and selection only; every claim about
    performance comes from live runs; the twin was checked against live runs.
81. **"Why did you change the model from v7 to v9?"** A different laptop; the twin and calibration do not transfer; v9 was
    trained for the second laptop under a new pre-registration.
82. **"Isn't the confidence fallback useless with thresholds of 0?"** It is implemented and tested, but the policy's
    probabilities were not calibrated as a correctness measure (decisions near 0.49 were correct), so health and SLA-risk
    rules gave clearer hand-back conditions.
83. **"Your SLO is end-to-end, but your guards use per-service latency. Isn't that inconsistent?"** The per-service SLO
    guard and Auto latency rule exist but are unused for the shop (no per-service SLO). Making Auto use end-to-end latency
    is the main future improvement.
84. **"How do you know the dashboard shows real values?"** It reads the same run files; missing values are "—"; the Comparison
    page uses the same code as the reports (`lab/benchmark.py`).
85. **"What would make FlexaScale beat a tuned HPA?"** Signals the HPA cannot use (latency, dependencies under real
    contention), heavier and more variable load where a fixed target is wrong for some services, and multi-node costs.
86. **"Why Stable-Baselines3 and not your own PPO?"** A tested, standard implementation reduces bugs and makes results
    reproducible; the custom part is the policy architecture and environment.
87. **"Your demo credentials are in Git."** Yes, for a local lab only; production would use Kubernetes Secrets from a
    vault.

### I.5 "Why did you choose …?"

* **GNN:** dependencies are a graph; message passing lets each decision see callers and callees; mask/padding supports
  different applications. (Honest: no measurable benefit here.)
* **PPO:** stable, few hyperparameters, works with discrete actions and shared actor-critic networks, standard in SB3;
  clipping suits a safety-critical setting.
* **Kubernetes:** the industry standard for microservices and the platform whose HPA we improve on.
* **Alibaba trace:** the largest public microservice trace with per-service CPU, memory, rate and latency; used to start
  (v1–v6); replaced by the twin when it did not transfer.
* **Minikube:** zero cost, full control, reproducible on student laptops.
* **This architecture (operator + freeze + Lease + Auto):** add-on without code changes, never two controllers, HPA always
  available.

---

## Part J — Explaining the project in 2, 5, 10 and 15 minutes

### J.1 Two minutes

"Microservice applications on Kubernetes are scaled by the Horizontal Pod Autoscaler, which looks at one service's CPU
with one fixed target. FlexaScale replaces that with a learned policy: every ten seconds it reads Prometheus telemetry,
builds ten unit-free features per service, passes them over the application's call graph with a graph neural network and
lets a PPO-trained policy propose a replica change per service. A safety layer bounds every change, a Kubernetes Lease and
an HPA freeze make sure only one controller acts on a service, and an Auto mode chooses per service whether FlexaScale or
the HPA should be in charge. We verified it live, including outages and crashes. In a pre-registered evaluation it used
about 7.5% fewer replica-hours than the default HPA, and it matched, but did not beat, a carefully tuned HPA."

### J.2 Five minutes

Add to the two-minute version: the shop (16 services, 25 edges, one PostgreSQL); the three HPA weaknesses with our numbers
(27 replicas kept for 5 minutes in a flash sale; brief CPU rises scaled in checkout-heavy load; the database-bound order
service); the twin (fitted to the shop, 2% replica-hour error), imitation then PPO, the gate; the safety guards; the Auto
rules; the verification table (Auto chose FlexaScale and Kubernetes confirmed 1→2 in 6 s / ready in 16 s; mixed ownership;
Prometheus cut; SIGKILL); the results table (default HPA vs tuned vs RL vs Auto); one limitation (per-laptop calibration
and CPU-only signal).

### J.3 Ten minutes (slide-by-slide outline)

1. Problem and motivation (1 min). 2. Objectives (0.5). 3. Literature and gap (1). 4. Architecture (1.5). 5. Features,
GNN and PPO with the real order-service decision (2). 6. Safety and Auto mode (1.5). 7. Evaluation design (1). 8.
Results: verification, pooled table, E1 chart (1.5). 9. Limitations and future work (0.5).

### J.4 Fifteen minutes (with live demo)

The ten-minute talk plus: a live Auto run in the Live lab (choose v7 on the Fedora laptop, flash sale, 25–40 users; point
at the proposal line, the ◆ marker, the desired step and the ready area); the Auto page's rule cards and ownership table;
the Comparison page with the tuned-HPA verdict; the Models page with the SHA-256; and the decision record of one step
(`decisions.jsonl`) to show explainability. Keep two minutes for the honest findings: on par with a tuned HPA, no
measurable graph benefit, and the database-bound service.
