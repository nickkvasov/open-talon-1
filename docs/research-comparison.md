# Open Talon Research And Ecosystem Comparison

This document is separate from the system reference and quickstart on purpose.

Use it when you need to place Open Talon in the broader ecosystem of multi-agent research, orchestration frameworks, and enterprise agent platforms. For the implemented Open Talon system, use [system-api-reference.md](./system-api-reference.md), [system-quickstart.md](./system-quickstart.md), and [../README.md](../README.md).

## Scope And Date

This comparison is anchored to the external sources available on April 22, 2026.

It compares:

- Open Talon as implemented in this repository
- research systems that shaped multi-agent collaboration patterns
- framework and cloud-platform offerings that emphasize orchestration, durability, and enterprise operations

## Open Talon In One Sentence

Open Talon is a local-first, tenant-aware collaboration platform where humans and agents are first-class participants inside shared workspaces, with durable execution, provider-backed observability, principal IAM, and a canonical Postgres audit and execution model.

## Comparison Summary

| System | Main abstraction | Strengths | Where Open Talon differs |
| --- | --- | --- | --- |
| Open Talon | shared workspace with humans and agents | tenant-aware collaboration, durable execution, IAM, audit, local-first operations | centers the product around shared workspace collaboration rather than around a single orchestration session or SDK graph |
| AutoGen | multi-agent conversation framework | flexible agent-to-agent conversation patterns, human/tool integration | Open Talon persists collaboration and execution state as platform records instead of treating conversation as the main runtime abstraction |
| MetaGPT | SOP-driven software-team simulation | role specialization, structured software workflows, assembly-line coordination | Open Talon supports role labels and routing but does not hard-wire one software-factory workflow into the platform model |
| Magentic-One | orchestrator with specialist agents | strong generalist task execution, replanning, modular specialists | Open Talon exposes modular agents too, but adds tenant boundaries, org/workspace controls, catalog resources, and audit surfaces around them |
| LangChain multi-agent | pattern catalog for agent composition | clear guidance on subagents, handoffs, skills, routers, and context engineering | Open Talon is a running system with persistence, auth, and operational boundaries, not only an orchestration pattern library |
| LangGraph | low-level stateful orchestration runtime | durable execution, human-in-the-loop, memory, production deployment support | Open Talon applies similar durability ideas inside a collaboration platform with workspace participants, IAM, and catalog resources |
| Microsoft Agent Framework | agent/workflow SDK with enterprise features | workflows, sessions, middleware, telemetry, type-safe routing | Open Talon emphasizes shared human-agent workspaces and platform governance rather than SDK-first workflow construction |
| Semantic Kernel orchestration | named orchestration patterns | sequential, concurrent, handoff, group chat, Magentic-style orchestration | Open Talon exposes fewer named orchestration primitives and instead uses threads, requests, selectors, and durable resume semantics |
| Azure orchestration guidance | architecture patterns for enterprise teams | practical decision rules for when to use single-agent vs multi-agent and which pattern fits | Open Talon follows the same bias toward justified complexity, but packages it into a self-hosted collaboration platform |
| Amazon Bedrock multi-agent | managed supervisor/collaborator teams | cloud-managed hierarchy, templates, monitoring, AWS integration | Open Talon keeps its data model, credentials, execution workers, and governance surfaces directly inspectable and self-hosted |
| OpenClaw | personal local-first agent runtime | multi-channel personal assistant, host-local gateway, skills, direct action across messaging surfaces | Open Talon is multi-user and workspace-centric, with tenancy, IAM, and collaboration records rather than a single-user assistant runtime |
| OpenHands | software-engineering agent platform | coding-focused agent SDK, CLI, GUI, cloud, and enterprise options with sandbox providers | Open Talon treats software work as one collaboration use case among many, and models people, agents, threads, and catalogs more broadly |
| Inspect | evaluation and agent harness | large eval library, agent bridge, tool support, sandboxes, external-agent integration | Open Talon is an operational collaboration platform, not primarily an eval framework |
| SWE-bench harness | benchmark evaluation harness | reproducible Docker-based patch evaluation and grading on software repositories | Open Talon can host or orchestrate development work, but benchmark grading is outside its core platform model |
| browser-use browser-harness | browser action harness | minimal self-healing CDP-based browser control and skill capture | Open Talon provides a platform for attaching tools and agents, not a single-purpose browser-control harness |

## Detailed Comparison

### AutoGen

[AutoGen](https://arxiv.org/abs/2308.08155) framed multi-agent systems around conversable agents that can mix LLMs, humans, and tools. That model was important because it made explicit agent-to-agent conversation the core programming surface.

Open Talon aligns with AutoGen on explicit participant interaction, but it moves the center of gravity from conversation framework to platform state:

- collaboration state is persisted in Postgres through workspaces, threads, participants, requests, tasks, runs, run steps, and tool calls
- organization membership, IAM bindings, and workspace-local participant materialization are first-class platform records
- audit is a canonical subsystem rather than an afterthought around conversation transcripts

Open Talon is therefore closer to an operational collaboration platform than to a conversation-first SDK.

### MetaGPT

[MetaGPT](https://arxiv.org/abs/2308.00352) pushes a software-team model built around standardized operating procedures, role specialization, and assembly-line coordination. It is especially relevant for software-engineering automation because it encodes the structure of a software organization into the prompts and workflow.

Open Talon can support that style of work, but it keeps the platform model more general:

- collaboration roles and capabilities are workspace-local labels for routing and discovery
- workspaces can define role metadata without turning that metadata into the authorization model
- tracked requests, participant selectors, and durable follow-up tasks let teams build SOP-like flows without forcing one built-in software-factory pattern

That makes Open Talon better suited to mixed human-agent collaboration beyond software-delivery pipelines alone.

### Magentic-One

[Magentic-One](https://arxiv.org/abs/2411.04468) demonstrates a modular orchestrator-plus-specialists design, with replanning and error recovery across web, file, and code tasks. Its relevance is that it shows a strong generalist multi-agent shape without retraining a monolithic system for every new domain.

Open Talon shares some of that modularity:

- agents are attachable catalog resources
- execution can resume from durable request and task state
- tool execution is isolated from the main gateway

The difference is scope. Magentic-One is primarily about task-solving architecture and benchmark performance. Open Talon adds organization boundaries, workspace-scoped participation, catalog publication, audit chains, provider configuration, and operator workflows around the agents.

### LangChain Multi-Agent Guidance

[LangChain's multi-agent guide](https://docs.langchain.com/oss/python/langchain/multi-agent/index) emphasizes that not every complex task needs multi-agent orchestration, and that the critical design problem is context engineering. It also categorizes practical patterns such as subagents, handoffs, skills, router flows, and custom workflows.

Open Talon is consistent with that guidance:

- plain thread messages remain first-class
- tracked requests are used when answer correlation matters
- durable task creation happens when the collaboration flow needs execution, not for every message

The difference is that Open Talon encodes these choices into a running product model with workspace state, participant attachment, IAM, and persistence rather than only a set of design patterns.

### LangGraph

[LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) presents itself as low-level infrastructure for long-running, stateful agents with durable execution, human-in-the-loop, memory, and deployment support. That maps closely to a core set of concerns Open Talon also addresses.

The overlap is strongest in:

- durable execution
- resumability
- human participation
- production debugging and observability

The difference is that LangGraph is an orchestration runtime. Open Talon adds a collaboration domain on top of those runtime concerns:

- organizations and workspaces
- human and agent participant materialization
- IAM and tenancy rules
- system and workspace catalogs for agents, tools, providers, assets, and repositories
- canonical audit chains

### Microsoft Agent Framework

[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) positions itself as a successor that combines AutoGen-style agent abstractions with Semantic Kernel's enterprise features and adds workflows for explicit multi-agent control. The current overview highlights agents, workflows, middleware, session state, and multi-provider support.

Open Talon overlaps with the enterprise concerns:

- stateful execution
- provider-backed integrations
- telemetry and operational visibility
- structured orchestration of multi-step work

The difference is the primary abstraction. Agent Framework is SDK-first and workflow-first. Open Talon is workspace-first:

- the primary shared object is a tenant-scoped workspace with humans and agents attached to it
- participants are visible collaboration entities, not only execution nodes
- authorization and collaboration routing are modeled separately

### Semantic Kernel Agent Orchestration

[Semantic Kernel agent orchestration](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/) exposes explicit patterns including sequential, concurrent, handoff, group chat, and Magentic-style orchestration through a unified invocation model.

Open Talon does not expose the same named orchestration taxonomy at the API surface. Instead, it composes similar outcomes from collaboration primitives:

- threads for shared context
- interaction requests for tracked multi-party questions
- selectors for routing by participant, collaboration role, or capability
- durable resume semantics when a request completes

That makes Open Talon more declarative at the collaboration layer and less explicit about named orchestration patterns.

### Azure Architecture Guidance

[Azure's AI agent orchestration patterns guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) argues that teams should begin with the lowest coordination complexity that solves the problem, and it lays out when to use sequential, concurrent, handoff, and group-chat patterns.

That guidance matches Open Talon's operating model closely:

- not every workflow should become multi-agent
- orchestration complexity should be justified
- shared state and resumption matter for long-running work
- enterprise systems need explicit security, reliability, and cost controls

Open Talon differs by implementing these concerns as part of a self-hosted collaboration platform rather than leaving them entirely to solution architecture.

### Amazon Bedrock Multi-Agent Collaboration

[Amazon Bedrock multi-agent collaboration](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html) uses a supervisor-plus-collaborator hierarchy where a supervisor plans, routes, and coordinates specialist agents. AWS also announced general availability on March 10, 2025, adding monitoring, observability, and infrastructure-template support in the managed service layer according to the [GA announcement](https://aws.amazon.com/about-aws/whats-new/2025/03/amazon-bedrock-multi-agent-collaboration/).

Open Talon overlaps with Bedrock in specialization and orchestration, but differs in operating model:

- Open Talon is self-hosted and local-first
- its credentials, secrets, execution workers, audit surfaces, and catalog records are directly inspectable
- its collaboration model is centered on shared threads and workspace participants, not only on managed supervisor-agent hierarchies

That makes Open Talon more operator-visible and platform-shapeable, while Bedrock emphasizes managed cloud primitives.

## Modern Harnesses And Runtimes

The current ecosystem also includes systems that are best understood as agent harnesses, task-specific runtimes, or evaluation infrastructure rather than as full collaboration platforms.

### OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) positions itself as a personal AI assistant that runs on your own devices, answers on messaging channels you already use, and is centered on a local Gateway control plane plus onboarding, channels, and skills. Its current public docs emphasize local-first operation, multi-channel routing, onboarding, skills, and a security model that distinguishes between host access for the main session and sandboxing for non-main sessions.

That gives OpenClaw a very different center of gravity from Open Talon:

- OpenClaw is optimized for a personal or single-user assistant that lives close to the user's devices and messaging channels
- Open Talon is optimized for shared workspaces containing multiple humans and agents inside explicit organization and workspace boundaries
- OpenClaw's workspace and session concepts are part of an assistant runtime and routing model
- Open Talon's workspace is the primary collaboration boundary for participants, permissions, catalogs, memory, requests, and execution

OpenClaw is therefore closer to a local agent operating system or assistant runtime. Open Talon is closer to a governed collaboration platform.

### OpenHands

[OpenHands](https://github.com/OpenHands/OpenHands) is centered on AI-driven software development. Its current project surface spans an SDK, CLI, local GUI, cloud, and enterprise deployments, and its docs describe sandbox providers for Docker, process, and remote execution.

Compared with Open Talon:

- OpenHands is strongly coding-task oriented
- Open Talon is general-purpose collaboration infrastructure that can support coding agents but is not limited to them
- OpenHands focuses on how an agent edits code and runs commands inside a sandbox
- Open Talon focuses on how humans and agents collaborate inside shared workspaces with durable records, IAM, audit, and system catalogs

OpenHands is the closer match when the primary problem is autonomous software engineering in a sandbox. Open Talon is the closer match when software engineering is one workflow inside a larger human-agent operating environment.

### Inspect

[Inspect](https://inspect.aisi.org.uk/) is an evaluation framework from the UK AI Security Institute. Its official docs describe a large built-in evaluation catalog, flexible tool support, agent evaluations, multi-agent primitives, external-agent bridging, and a sandboxing system that can run untrusted code across several backends. Its agent docs also make clear that Inspect can evaluate built-in agents, custom agents, multi-agent compositions, and bridged external agents such as CLI-based coding agents.

This makes Inspect complementary to Open Talon rather than directly competitive:

- Inspect is primarily about evaluation design, execution, logging, and comparison
- Open Talon is primarily about production collaboration state, execution coordination, tenant boundaries, and operator control
- Inspect can wrap external agents and sandboxes for benchmarking or assessment
- Open Talon can provide the shared collaboration and runtime context in which agents do work

If you need systematic agent evaluation, Inspect is the stronger fit. If you need a persistent human-agent collaboration platform, Open Talon is the stronger fit.

### SWE-bench Harness

The [SWE-bench harness](https://www.swebench.com/SWE-bench/reference/harness/) is a Docker-based evaluation harness for software-engineering benchmarks. Its official reference describes reproducible containerized evaluation, layered images, patch application, test execution, grading, and report generation.

This is a narrower and more benchmark-oriented system than Open Talon:

- SWE-bench harness is designed to answer whether a predicted patch resolves a benchmark task
- Open Talon is designed to coordinate people, agents, tools, memory, and execution in an ongoing workspace
- SWE-bench harness optimizes for repeatable measurement
- Open Talon optimizes for operational collaboration and durable workflow state

The systems can coexist: SWE-bench harness is useful for measuring coding agents that might themselves run inside or alongside a broader collaboration platform.

### browser-use browser-harness

The [browser-use browser-harness](https://github.com/browser-use/browser-harness) describes itself as a thin, self-healing browser harness built directly on CDP, with the agent able to edit helper functions mid-task and accumulate site-specific skills over time.

That puts it in a different category from Open Talon:

- browser-harness is a domain-specific action substrate for browser work
- Open Talon is a multi-surface collaboration platform where browser control would be one tool capability among many
- browser-harness minimizes abstraction between the model and the browser
- Open Talon intentionally adds governance layers such as participant attachment, IAM, catalogs, trust levels, and audit

This kind of harness is a useful building block for tools. It is not, by itself, a replacement for the collaboration, tenancy, and operating model Open Talon provides.

## Modern Enterprise Multi-Agent Systems

The enterprise market has converged around a few recurring product shapes:

- managed cloud agent platforms
- workflow-native enterprise control towers
- automation suites that orchestrate agents, robots, and people together

Open Talon overlaps with all three categories in some respects, but it keeps a distinct center of gravity: a self-hosted collaboration platform with humans and agents as first-class participants inside governed workspaces.

### Enterprise Comparison Summary

| System | Enterprise center of gravity | What the vendor emphasizes | Where Open Talon differs |
| --- | --- | --- | --- |
| Microsoft Agent Framework + Azure guidance | SDK and workflow control for enterprise agents | workflows, middleware, telemetry, type-safe orchestration, agent vs workflow decision rules | Open Talon is workspace-first and product-first rather than SDK-first |
| Amazon Bedrock multi-agent | managed supervisor/collaborator teams | hierarchical collaboration, templates, monitoring, AWS-managed infrastructure | Open Talon keeps runtime, data model, audit, and secrets directly operator-controlled |
| Google Vertex AI Agent Builder / Agent Engine | full-stack managed build, deploy, govern platform | ADK, Agent Engine runtime, sessions, memory, observability, governance, evaluation | Open Talon is collaboration-native and self-hosted instead of a vendor-managed deployment stack |
| Salesforce Agentforce | CRM and enterprise-experience agent platform | build, test, deploy, manage, and orchestrate agents with enterprise data and apps | Open Talon is not anchored to one business application cloud or customer-data platform |
| ServiceNow AI Agent Orchestrator | platform control tower for enterprise workflows | orchestrator, studio, fabric, control tower, built-in workflow/data platform | Open Talon models participants, threads, and workspace catalogs directly instead of centering everything on workflow orchestration inside one SaaS platform |
| IBM watsonx Orchestrate | open multi-agent orchestration layer for business systems | open integration, multi-agent orchestration, builder, catalog, governance, hybrid deployment | Open Talon is narrower in vendor ecosystem reach but stronger on local-first inspectability and collaboration-domain modeling |
| UiPath Maestro | process orchestration across agents, robots, and people | BPMN/DMN process modeling, HITL, governance, process monitoring, hybrid workforce orchestration | Open Talon is collaboration-centric rather than process-model-centric, and does not assume RPA as a foundational primitive |

### Cloud Agent Platforms

#### Microsoft Agent Framework

[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) frames enterprise agent systems around agents plus workflows, with middleware, session state, telemetry, and explicit control over multi-agent execution paths. The companion [Azure orchestration guidance](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns) pushes teams to justify multi-agent complexity and choose patterns deliberately.

Open Talon shares the emphasis on durability, operational control, and justified orchestration complexity. The difference is packaging:

- Microsoft's center of gravity is the developer framework and workflow runtime
- Open Talon's center of gravity is the shared workspace and the collaboration records around it

In other words, Agent Framework is a strong enterprise substrate for building agent applications. Open Talon is a stronger fit when the application itself is a governed human-agent collaboration environment.

#### Amazon Bedrock Multi-Agent Collaboration

[Amazon Bedrock multi-agent collaboration](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html) emphasizes supervisor-led teams of specialist agents, while the [GA announcement](https://aws.amazon.com/about-aws/whats-new/2025/03/amazon-bedrock-multi-agent-collaboration/) highlights templates, monitoring, and observability in the managed AWS environment.

Compared with Open Talon:

- Bedrock is managed-cloud-first
- Open Talon is self-hosted and local-first
- Bedrock centers orchestration around supervisor and collaborator agents
- Open Talon centers collaboration around workspaces, participants, threads, requests, and durable execution state

Bedrock is the stronger fit when AWS-managed infrastructure and cloud-native scaling are the main requirement. Open Talon is stronger when direct operator control, inspectability, and platform-owned collaboration state matter more.

#### Google Vertex AI Agent Builder And Agent Engine

[Vertex AI Agent Builder](https://cloud.google.com/products/agent-builder) is described by Google as a platform to build, scale, and govern enterprise-grade agents. The official docs position it as a full-stack suite spanning [ADK](https://docs.cloud.google.com/agent-builder/agent-development-kit/overview), [Agent Engine](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/overview), and other discovery and design surfaces. Google emphasizes managed runtime, sessions, memory, observability, governance, and support for multi-agent workflows plus protocols such as Agent2Agent.

Compared with Open Talon:

- Google offers a broad managed lifecycle for building and running agents in production
- Open Talon offers a governed collaboration platform where running agents are one part of a larger workspace system
- Google focuses on developer choice plus managed deployment infrastructure
- Open Talon focuses on participant-aware collaboration, tenancy, IAM, audit, and self-hosted operations

Google's platform is closer to an enterprise agent PaaS. Open Talon is closer to a collaboration control plane with its own runtime.

### Workflow-Native Enterprise Platforms

#### Salesforce Agentforce

[Salesforce Agentforce](https://www.salesforce.com/agentforce/) presents itself as an enterprise agent platform for building, testing, deploying, managing, and orchestrating agents at scale across humans, applications, AI agents, and data.

That makes Agentforce powerful inside enterprises already centered on Salesforce data and workflows. The main difference from Open Talon is platform anchoring:

- Agentforce is deeply coupled to the Salesforce enterprise application and data ecosystem
- Open Talon is provider-neutral and not anchored to one CRM, help desk, or enterprise app cloud
- Agentforce treats enterprise data and experience flows as the core operating surface
- Open Talon treats collaboration workspaces, participant materialization, catalogs, and audit as the core operating surface

If the enterprise wants agents to live inside Salesforce-centered customer and employee workflows, Agentforce is a natural fit. If the enterprise wants a more general collaboration substrate outside a single application cloud, Open Talon is closer to that need.

#### ServiceNow AI Agent Orchestrator

ServiceNow positions [AI Agents](https://www.servicenow.com/products/ai-agents.html) and the broader platform as built-in, not bolted on. Its public material describes AI Agent Orchestrator as a control tower and emphasizes coordination across tasks, systems, and departments, while AI Agent Fabric and the broader platform provide data, workflow, and agent integration surfaces.

Compared with Open Talon:

- ServiceNow is workflow-platform-native and deeply tied to enterprise operations on the Now Platform
- Open Talon is collaboration-platform-native and models shared human-agent work at the workspace/thread level
- ServiceNow emphasizes central control over agent sprawl across departments
- Open Talon emphasizes explicit participant attachment, authorization, catalog scoping, and durable collaboration records

ServiceNow is strongest where the enterprise already standardizes on workflow automation and service operations in the Now Platform. Open Talon is stronger where the organization wants a standalone collaboration operating layer that is not subordinate to a single SaaS platform.

### Orchestration And Automation Suites

#### IBM watsonx Orchestrate

[IBM watsonx Orchestrate](https://www.ibm.com/products/watson-orchestrate) emphasizes multi-agent orchestration, an agent and tool builder, prebuilt agents and tools, governance, observability, and hybrid deployment. IBM's developer-facing material also describes agents as being able to include collaborators and to integrate external agents from other platforms.

Compared with Open Talon:

- IBM emphasizes interoperability across an enterprise agent ecosystem
- Open Talon emphasizes local-first inspectability, tenant-aware collaboration state, and explicit participation boundaries
- IBM is oriented toward enterprise-wide orchestration across many existing systems
- Open Talon is oriented toward operating collaboration directly inside the platform

watsonx Orchestrate is broader as an enterprise integration and orchestration story. Open Talon is tighter as a collaboration system with explicit governance in its own domain model.

#### UiPath Maestro

[UiPath Maestro](https://docs.uipath.com/maestro/automation-cloud/latest/user-guide/introduction-to-maestro) is positioned as a cloud-native orchestration platform that unifies automation, AI agents, and human interactions in end-to-end business processes. The [value proposition](https://docs.uipath.com/maestro/automation-cloud/latest/user-guide/value-proposition) and related docs emphasize agents, robots, and people working together with BPMN modeling, governance, HITL, monitoring, retries, and optimization.

Compared with Open Talon:

- UiPath starts from process orchestration and hybrid workforce execution
- Open Talon starts from collaboration spaces, participants, threads, and execution handoff
- UiPath assumes close integration with automation and RPA assets
- Open Talon assumes agents, tools, catalogs, and collaboration primitives rather than BPMN-led process modeling

UiPath Maestro is strongest when the enterprise wants agentic automation stitched directly into broader RPA/process programs. Open Talon is stronger when the enterprise wants a collaboration-native platform rather than a process-model-native platform.

## Platform Versus Harness

One practical way to think about the current landscape is:

- research systems explore collaboration patterns and agent architectures
- harnesses focus on execution substrates, evaluation, or narrow task environments
- platforms package collaboration, governance, persistence, and operations into one system

Open Talon belongs most clearly in the platform category.

It can borrow ideas from research systems and integrate or emulate harness-like capabilities, but its defining value is the combination of:

- shared human-agent workspaces
- tenant-aware authorization
- durable collaboration and execution records
- system catalogs and publication workflows
- canonical audit and operator visibility
- local-first, self-hosted infrastructure control

## Practical Positioning

If you are choosing among these systems, the current shape of Open Talon is strongest when you need:

- a shared human-agent collaboration surface rather than only an orchestration SDK
- tenant-aware organization and workspace boundaries
- platform-owned authorization instead of relying on external IdP claims for business permissions
- durable execution records tied directly to collaboration artifacts
- canonical audit and operator visibility in the same platform
- local-first or self-hosted control over infrastructure and data paths

Open Talon is less aligned if your main need is:

- a minimal embedding library for orchestration inside an existing application
- a fully managed cloud agent product where the provider owns most operational concerns
- a benchmark-oriented research framework with minimal platform and governance requirements

## Sources

- [Open Talon README](../README.md)
- [Open Talon system API reference](./system-api-reference.md)
- [AutoGen paper](https://arxiv.org/abs/2308.08155)
- [MetaGPT paper](https://arxiv.org/abs/2308.00352)
- [Magentic-One paper](https://arxiv.org/abs/2411.04468)
- [LangChain multi-agent guide](https://docs.langchain.com/oss/python/langchain/multi-agent/index)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Semantic Kernel agent orchestration](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/)
- [Azure AI agent orchestration patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- [Amazon Bedrock multi-agent collaboration docs](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html)
- [Amazon Bedrock multi-agent collaboration GA announcement](https://aws.amazon.com/about-aws/whats-new/2025/03/amazon-bedrock-multi-agent-collaboration/)
- [OpenClaw repository](https://github.com/openclaw/openclaw)
- [OpenClaw docs](https://docs.openclaw.ai)
- [OpenHands repository](https://github.com/OpenHands/OpenHands)
- [OpenHands sandbox overview](https://docs.openhands.dev/openhands/usage/sandboxes/overview)
- [Inspect overview](https://inspect.aisi.org.uk/)
- [Inspect agents guide](https://inspect.aisi.org.uk/agents.html)
- [SWE-bench harness reference](https://www.swebench.com/SWE-bench/reference/harness/)
- [browser-use browser-harness repository](https://github.com/browser-use/browser-harness)
- [Google Vertex AI Agent Builder product page](https://cloud.google.com/products/agent-builder)
- [Google ADK overview](https://docs.cloud.google.com/agent-builder/agent-development-kit/overview)
- [Google Agent Engine overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/overview)
- [Salesforce Agentforce](https://www.salesforce.com/agentforce/)
- [ServiceNow AI Agents](https://www.servicenow.com/products/ai-agents.html)
- [IBM watsonx Orchestrate](https://www.ibm.com/products/watson-orchestrate)
- [UiPath Maestro overview](https://docs.uipath.com/maestro/automation-cloud/latest/user-guide/introduction-to-maestro)
- [UiPath Maestro value proposition](https://docs.uipath.com/maestro/automation-cloud/latest/user-guide/value-proposition)
