import React, { useState } from 'react';
import { 
  Terminal, 
  Copy, 
  Check, 
  AlertTriangle, 
  ShieldCheck, 
  Cpu, 
  ArrowRight, 
  Layers, 
  Workflow, 
  HelpCircle,
  Code2,
  FileCode,
  Download
} from 'lucide-react';

export const DocsCenter: React.FC = () => {
  const [activeSection, setActiveSection] = useState('intro');
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(id);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const sections = [
    { id: 'intro', label: '1. Introduction' },
    { id: 'what-is-sceptic', label: '2. What is Sceptic?' },
    { id: 'how-it-works', label: '3. How Sceptic Works' },
    { id: 'architecture', label: '4. System Architecture' },
    { id: 'agents', label: '5. Verification Agents' },
    { id: 'fact-checker', label: '6. Fact-Checker' },
    { id: 'blind-tester', label: '7. Blind Tester' },
    { id: 'security-guard', label: '8. Security Guard' },
    { id: 'synthesizer', label: '9. Report Synthesizer' },
    { id: 'trust-score', label: '10. Trust Score Methodology' },
    { id: 'cli', label: '11. CLI Overview' },
    { id: 'cli-install', label: '12. CLI Installation (Source)' },
    { id: 'cli-config', label: '13. Environment & Configuration' },
    { id: 'first-audit', label: '14. First Audit Guide' },
    { id: 'cli-commands', label: '15. CLI Commands Reference' },
    { id: 'web-dashboard', label: '16. Web Dashboard' },
    { id: 'api-overview', label: '17. API Overview' },
    { id: 'troubleshooting', label: '18. Troubleshooting' },
    { id: 'development', label: '19. Development Information' },
  ];

  return (
    <div className="flex flex-col lg:flex-row items-start gap-8">
      {/* Table of contents sidebar */}
      <div className="w-full lg:w-64 shrink-0 bg-slate-900 border border-slate-800 rounded-xl p-4 sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 px-2">
          Documentation Index
        </h3>
        <nav className="space-y-1 text-xs">
          {sections.map((sec) => (
            <button
              key={sec.id}
              onClick={() => setActiveSection(sec.id)}
              className={`w-full text-left px-2.5 py-1.5 rounded-lg transition-colors font-medium truncate ${
                activeSection === sec.id
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              {sec.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Main Documentation Article Content */}
      <div className="flex-1 min-w-0 bg-slate-900 border border-slate-800 rounded-xl p-6 sm:p-8 space-y-10 text-xs sm:text-sm text-slate-300 leading-relaxed font-sans">
        
        {/* Section: Intro */}
        {activeSection === 'intro' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 1</span>
              <span>·</span>
              <span>Overview</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Introduction</h2>
            <p>
              Welcome to the <strong>Sceptic Developer Documentation Center</strong>. Sceptic is an independent, automated AI-generated code verification system created to objectively test, fact-check, and audit code before it reaches production branches.
            </p>
            <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs">
              <strong>Core Mission:</strong> AI code generators frequently hallucinate library signatures, write subtle security bugs, or fail unspoken specification requirements. Sceptic operates as an autonomous, adversarial verification gatekeeper.
            </div>
          </section>
        )}

        {/* Section: What is Sceptic */}
        {activeSection === 'what-is-sceptic' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 2</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">What is Sceptic?</h2>
            <p>
              Modern software teams increasingly ingest AI-generated pull requests and automated refactorings. However, evaluating AI code requires more than simple linting:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-slate-300">
              <li><strong>Hallucinated APIs:</strong> LLMs often invoke methods that sound plausible but do not exist in installed third-party packages or standard library versions.</li>
              <li><strong>Confirmation Bias in Self-Testing:</strong> When the same LLM writes both the code and unit tests, it reproduces its own logic flaws and blind spots.</li>
              <li><strong>Subtle Security Vulnerabilities:</strong> LLMs regularly introduce insecure string interpolations, command execution, and hardcoded secrets.</li>
            </ul>
            <p>
              Sceptic provides a multi-agent verification pipeline that is completely independent of the authoring LLM.
            </p>
          </section>
        )}

        {/* Section: How Sceptic Works */}
        {activeSection === 'how-it-works' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 3</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">How Sceptic Works</h2>
            <p>
              Sceptic executes across two primary workflows that share the exact same underlying verification engine:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-4 font-mono text-xs">
              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-emerald-400 block mb-2 font-sans text-sm">CLI In-Process Workflow</span>
                Developer Terminal<br />
                ↓<br />
                <code className="text-emerald-400">sceptic audit &lt;path&gt;</code><br />
                ↓<br />
                Shared Audit Service<br />
                ↓<br />
                In-Process Orchestrator & Agents<br />
                ↓<br />
                Rich UI Output & Exit Codes
              </div>
              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-blue-400 block mb-2 font-sans text-sm">Webhook Asynchronous Workflow</span>
                GitHub Pull Request Webhook<br />
                ↓<br />
                FastAPI (<code className="text-blue-400">POST /webhook</code>)<br />
                ↓<br />
                Celery Worker (Redis Broker)<br />
                ↓<br />
                PostgreSQL Persistence<br />
                ↓<br />
                Web Dashboard Inspection
              </div>
            </div>
          </section>
        )}

        {/* Section: System Architecture */}
        {activeSection === 'architecture' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 4</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">System Architecture</h2>
            <p>
              Sceptic uses a <strong>Fan-Out / Fan-In</strong> multi-agent architecture. When an audit is triggered, three independent verification agents analyze the code simultaneously:
            </p>
            <pre className="p-4 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 font-mono text-xs overflow-x-auto leading-relaxed">
{`Audit Target (File / PR / Directory)
           │
           ▼
    Audit Orchestrator (Fan-Out)
 ┌─────────┼─────────────────────────┐
 ▼         ▼                         ▼
Fact-    Blind-Tester          Security-Guard
Checker  (ISOLATED SPEC)       (Semgrep, Bandit, LLM)
 │         │                         │
 └─────────┼─────────────────────────┘
           ▼
   Report Synthesizer (Fan-In)
           │
           ▼
 Deterministic Trust Score (0-100)`}
            </pre>
            <p>
              This isolation guarantees that failures or timeouts in one agent do not halt the entire pipeline.
            </p>
          </section>
        )}

        {/* Section: Verification Agents */}
        {activeSection === 'agents' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 5</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Verification Agents</h2>
            <p>
              Sceptic employs three specialized agents, each addressing a distinct vulnerability surface:
            </p>
            <div className="space-y-3">
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-white block">1. Fact-Checker Agent</span>
                <span className="text-slate-400 text-xs">Deterministic Python AST parser verifying real runtime API existence.</span>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-white block">2. Blind Tester Agent</span>
                <span className="text-slate-400 text-xs">Specification-isolated LLM generating blind unit tests executed in a clean sandbox.</span>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-white block">3. Security Guard Agent</span>
                <span className="text-slate-400 text-xs">Static analyzer utilizing Bandit and Semgrep, augmented by LLM contextual filtering.</span>
              </div>
            </div>
          </section>
        )}

        {/* Section: Fact Checker */}
        {activeSection === 'fact-checker' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 6</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Fact-Checker Agent</h2>
            <p>
              The Fact-Checker is <strong>completely deterministic</strong>. It does <em>not</em> rely on an LLM to guess whether an API exists:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li>Parses source code into an Abstract Syntax Tree (<code className="text-emerald-400">ast.parse</code>).</li>
              <li>Resolves top-level and alias imports (<code className="text-emerald-400">import ... as</code>, <code className="text-emerald-400">from ... import</code>).</li>
              <li>Dynamically loads installed modules via <code className="text-emerald-400">importlib</code> and inspects attributes using <code className="text-emerald-400">dir()</code>.</li>
              <li>Extracts callable parameter signatures via <code className="text-emerald-400">inspect.signature()</code> and validates positional, keyword, and varargs calls.</li>
              <li>Flags non-existent methods, missing mandatory arguments, or unexpected keyword parameters with exact line numbers.</li>
            </ul>
          </section>
        )}

        {/* Section: Blind Tester */}
        {activeSection === 'blind-tester' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 7</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Blind Tester Agent (Information Isolation)</h2>
            <p>
              The Blind Tester enforces an architectural constraint called <strong>Information Isolation</strong>:
            </p>
            <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
              <strong>Strict Isolation Rule:</strong> The test-generation LLM is NEVER provided the implementation source code. It only receives function names, docstrings, parameter types, and PR descriptions.
            </div>
            <p>
              Because the LLM has not seen the author's implementation, it cannot fall prey to confirmation bias. Once independent specification tests are generated, an isolated subprocess executes pytest against the target module. Any failure is recorded as a high-severity specification violation.
            </p>
          </section>
        )}

        {/* Section: Security Guard */}
        {activeSection === 'security-guard' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 8</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Security Guard Agent</h2>
            <p>
              The Security Guard runs dual static analysis scanners:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li><strong>Bandit:</strong> Finds common Python security risks such as <code className="text-emerald-400">eval()</code>, <code className="text-emerald-400">exec()</code>, unsafe YAML loading, and hardcoded credentials.</li>
              <li><strong>Semgrep:</strong> Runs pattern-matched rules (<code className="text-emerald-400">worker/semgrep_rules.yaml</code>) detecting raw SQL string formatting, shell injections (<code className="text-emerald-400">subprocess.run(shell=True)</code>), and weak cryptographic algorithms.</li>
              <li><strong>Groq Contextual Analysis:</strong> High-severity findings undergo automated analysis via LLM to verify whether the vulnerability is real or an intentional test mock.</li>
            </ul>
          </section>
        )}

        {/* Section: Report Synthesizer */}
        {activeSection === 'synthesizer' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 9</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Report Synthesizer</h2>
            <p>
              The Report Synthesizer collects the output from all three agents and standardizes them into structured findings matching the <code className="text-emerald-400">AgentFinding</code> schema:
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Deduplicates overlapping scanner reports.</li>
              <li>Calculates severity breakdowns (CRITICAL, HIGH, MEDIUM, LOW, UNRESOLVED).</li>
              <li>Passes finding counts into the deterministic Trust Score algorithm.</li>
              <li>Synthesizes a human-readable summary of risk.</li>
            </ul>
          </section>
        )}

        {/* Section: Trust Score */}
        {activeSection === 'trust-score' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 10</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Trust Score Methodology</h2>
            <p>
              The Trust Score evaluates code objectively on a scale of <strong>0 to 100</strong>:
            </p>
            <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-2 font-mono text-xs">
              <div className="text-white font-bold">Base Score: 100 Points</div>
              <div className="text-red-400">CRITICAL Finding: -35 points per issue (RCE, Injection, AWS Secrets)</div>
              <div className="text-orange-400">HIGH Finding: -20 points per issue (Spec failure, Non-existent API)</div>
              <div className="text-yellow-400">MEDIUM Finding: -10 points per issue (Parameter mismatch, Security warning)</div>
              <div className="text-blue-400">LOW Finding: -3 points per issue (Informational notice)</div>
              <div className="text-slate-400">UNRESOLVED / ERROR: -5 points (Ambiguous dynamic call)</div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs">
              <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300">
                <span className="font-bold block text-sm">85 - 100</span>
                <span className="font-semibold">APPROVE</span>: Code meets quality and safety standards.
              </div>
              <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-300">
                <span className="font-bold block text-sm">65 - 84</span>
                <span className="font-semibold">REQUEST_CHANGES</span>: Non-critical warnings detected.
              </div>
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300">
                <span className="font-bold block text-sm">0 - 64</span>
                <span className="font-semibold">BLOCK</span>: Critical vulnerabilities or failed spec tests.
              </div>
            </div>
          </section>
        )}

        {/* Section: CLI Overview */}
        {activeSection === 'cli' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 11</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">CLI Overview</h2>
            <p>
              The Sceptic CLI enables developers to run the full verification suite directly in their local terminal or inside CI runners before committing or pushing changes:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li><strong>Zero background dependency:</strong> Runs directly in-process without requiring Docker, PostgreSQL, or Celery.</li>
              <li><strong>Rich Terminal Output:</strong> Formatted tables, severity breakdowns, live spinner, and clear verdicts.</li>
              <li><strong>Scriptable Exit Codes:</strong> Returns standard POSIX exit codes for automated shell scripting.</li>
            </ul>
          </section>
        )}

        {/* Section: CLI Installation */}
        {activeSection === 'cli-install' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 12</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Install Sceptic CLI (Source Installation)</h2>
            <p>
              The Sceptic CLI is packaged using <code className="text-emerald-400">pyproject.toml</code> with setuptools. Install it in editable mode from the project repository:
            </p>
            
            <h3 className="text-sm font-bold text-white pt-2">Prerequisites:</h3>
            <ul className="list-disc pl-5 space-y-1 text-slate-300">
              <li>Python 3.10+ (Python 3.12 recommended)</li>
              <li>pip</li>
              <li>Git</li>
            </ul>

            <h3 className="text-sm font-bold text-white pt-2">Installation Steps:</h3>
            
            {/* PowerShell / Windows */}
            <div className="space-y-1.5">
              <span className="font-semibold text-slate-300">Windows (PowerShell):</span>
              <div className="relative group">
                <pre className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-emerald-400 font-mono text-xs overflow-x-auto">
{`# 1. Navigate to project root
cd D:\\Projects\\Sceptic

# 2. Activate virtual environment
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\\venv\\Scripts\\Activate.ps1

# 3. Install Sceptic CLI in editable mode
pip install -e .`}
                </pre>
                <button
                  onClick={() => copyToClipboard('pip install -e .', 'win-install')}
                  className="absolute right-3 top-3 p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                >
                  {copiedIndex === 'win-install' ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                </button>
              </div>
            </div>

            {/* Linux / macOS */}
            <div className="space-y-1.5 pt-2">
              <span className="font-semibold text-slate-300">Linux / macOS (Bash / Zsh):</span>
              <div className="relative group">
                <pre className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-emerald-400 font-mono text-xs overflow-x-auto">
{`# 1. Activate virtual environment
source venv/bin/activate

# 2. Install Sceptic CLI in editable mode
pip install -e .`}
                </pre>
              </div>
            </div>

            <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-2">
              <span className="font-bold text-white block">Verify Installation:</span>
              <code className="text-emerald-400 font-mono">sceptic --help</code>
              <p className="text-xs text-slate-400">
                You should see the Sceptic CLI help menu displaying the <code className="text-slate-300 font-mono">audit</code> command.
              </p>
            </div>
          </section>
        )}

        {/* Section: Configuration */}
        {activeSection === 'cli-config' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 13</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Environment & Configuration</h2>
            <p>
              Sceptic loads environment variables from a root <code className="text-emerald-400">.env</code> file:
            </p>
            <pre className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 font-mono text-xs overflow-x-auto">
{`# .env configuration example (DO NOT COMMIT SECRETS TO GIT)
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
DATABASE_URL=postgresql://sceptic_user:sceptic_pass@localhost:5432/sceptic_db
REDIS_URL=redis://localhost:6379/0
ENVIRONMENT=development`}
            </pre>
            <div className="p-3.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
              <strong>Security Warning:</strong> Never commit API keys or passwords to version control. Keep <code className="font-mono">.env</code> in your <code className="font-mono">.gitignore</code> file.
            </div>
          </section>
        )}

        {/* Section: First Audit */}
        {activeSection === 'first-audit' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 14</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">First Audit Guide</h2>
            <p>Follow these steps to run your very first Sceptic audit:</p>

            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <span className="h-6 w-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-xs shrink-0">1</span>
                <div>
                  <span className="font-bold text-white block">Create a test Python script:</span>
                  <pre className="p-3 rounded bg-slate-950 border border-slate-800 text-slate-300 font-mono text-xs mt-1">
{`# demo.py
def calculate_area(length: float, width: float) -> float:
    """Calculate the area of a rectangle."""
    return length * width`}
                  </pre>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <span className="h-6 w-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-xs shrink-0">2</span>
                <div>
                  <span className="font-bold text-white block">Run the Sceptic audit command:</span>
                  <code className="text-emerald-400 font-mono block mt-1">sceptic audit demo.py</code>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <span className="h-6 w-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-xs shrink-0">3</span>
                <div>
                  <span className="font-bold text-white block">Inspect the output:</span>
                  <p className="text-slate-400 text-xs mt-1">
                    You will see a live spinner, agent execution confirmation, zero findings, a Trust Score of 100/100, and a green <strong className="text-emerald-400">APPROVE</strong> verdict.
                  </p>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Section: CLI Commands Reference */}
        {activeSection === 'cli-commands' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 15</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">CLI Commands Reference</h2>
            <div className="space-y-4 font-mono text-xs">
              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5">
                <div className="text-emerald-400 font-bold">sceptic audit &lt;path&gt;</div>
                <p className="text-slate-400 font-sans text-xs">
                  Audits a single Python file (<code className="font-mono">.py</code>) or recursively walks a directory, excluding cache and virtualenv folders.
                </p>
              </div>

              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5">
                <div className="text-emerald-400 font-bold">sceptic audit &lt;path&gt; --verbose / -v</div>
                <p className="text-slate-400 font-sans text-xs">
                  Displays finding evidence snippets and execution trace details for every reported issue.
                </p>
              </div>

              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5">
                <div className="text-emerald-400 font-bold">sceptic audit &lt;path&gt; --json</div>
                <p className="text-slate-400 font-sans text-xs">
                  Emits raw structured JSON output without Rich terminal formatting. Ideal for CI scripts and pipe workflows.
                </p>
              </div>
            </div>

            <h3 className="text-sm font-bold text-white pt-2">Exit Codes:</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-2">Code</th>
                    <th className="p-2">Meaning</th>
                    <th className="p-2">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-300">
                  <tr>
                    <td className="p-2 font-bold text-emerald-400">0</td>
                    <td className="p-2">SUCCESS</td>
                    <td className="p-2 font-sans">Audit passed with APPROVE verdict (Trust Score ≥ 85).</td>
                  </tr>
                  <tr>
                    <td className="p-2 font-bold text-yellow-400">1</td>
                    <td className="p-2">AUDIT FAILURE</td>
                    <td className="p-2 font-sans">Issues detected (REQUEST_CHANGES or BLOCK, Trust Score &lt; 85).</td>
                  </tr>
                  <tr>
                    <td className="p-2 font-bold text-red-400">2</td>
                    <td className="p-2">CLI ERROR</td>
                    <td className="p-2 font-sans">Invalid path, non-Python file, permission error, or runtime exception.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Section: Web Dashboard */}
        {activeSection === 'web-dashboard' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 16</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Web Dashboard</h2>
            <p>
              The React Web Dashboard provides a single-pane-of-glass interface for monitoring code verification:
            </p>
            <ul className="list-disc pl-5 space-y-2">
              <li><strong>Overview:</strong> High-level metrics on total audits, verified runs, and global finding distributions.</li>
              <li><strong>Audits List:</strong> Searchable and filterable history of pull request and CLI audit runs.</li>
              <li><strong>Audit Details:</strong> Granular inspection of agent results, evidence traces, and synthesizer summaries.</li>
              <li><strong>Global Findings:</strong> Filter findings across all repositories by severity (Critical, High, Medium, Low) and Agent.</li>
            </ul>
          </section>
        )}

        {/* Section: API Overview */}
        {activeSection === 'api-overview' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 17</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">API Overview</h2>
            <div className="space-y-3 font-mono text-xs">
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-emerald-400 font-bold">GET /health</span>
                <span className="text-slate-400 font-sans block mt-1">Checks API status and PostgreSQL/Redis connectivity.</span>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-emerald-400 font-bold">GET /audits?skip=0&limit=100</span>
                <span className="text-slate-400 font-sans block mt-1">Returns paginated audit run records.</span>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-emerald-400 font-bold">GET /audits/&#123;id&#125;</span>
                <span className="text-slate-400 font-sans block mt-1">Returns a single audit run with its agent findings.</span>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="text-blue-400 font-bold">POST /webhook</span>
                <span className="text-slate-400 font-sans block mt-1">Ingests GitHub PR webhook payloads and enqueues Celery audits.</span>
              </div>
            </div>
          </section>
        )}

        {/* Section: Troubleshooting */}
        {activeSection === 'troubleshooting' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 18</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Troubleshooting Guide</h2>
            <div className="space-y-3">
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-red-400 block">Command 'sceptic' not found</span>
                <span className="text-slate-300 block mt-1">
                  Ensure the virtual environment is activated (<code className="font-mono text-emerald-400">.\venv\Scripts\Activate.ps1</code> or <code className="font-mono text-emerald-400">source venv/bin/activate</code>) and you ran <code className="font-mono text-emerald-400">pip install -e .</code>.
                </span>
              </div>

              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-red-400 block">Bandit / Semgrep executable not found</span>
                <span className="text-slate-300 block mt-1">
                  Ensure <code className="font-mono text-emerald-400">bandit</code> and <code className="font-mono text-emerald-400">semgrep</code> are installed in your virtual environment: <code className="font-mono text-emerald-400">pip install bandit semgrep</code>.
                </span>
              </div>

              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800">
                <span className="font-bold text-red-400 block">Groq API Rate Limit or Missing Key</span>
                <span className="text-slate-300 block mt-1">
                  If <code className="font-mono">GROQ_API_KEY</code> is unset, the Blind Tester and Security Guard fallback gracefully to deterministic verification. Set your key in <code className="font-mono">.env</code> to enable LLM contextual review.
                </span>
              </div>
            </div>
          </section>
        )}

        {/* Section: Development Info */}
        {activeSection === 'development' && (
          <section className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs uppercase tracking-wider">
              <span>Section 19</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Development Information</h2>
            <p>
              To run automated tests and build the application locally:
            </p>
            <pre className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-emerald-400 font-mono text-xs overflow-x-auto">
{`# Run full automated test suite across all modules (47 tests)
pytest backend/test_api.py worker/ cli/ -v

# Start Vite React frontend development server
cd frontend
npm run dev

# Start FastAPI backend server
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`}
            </pre>
          </section>
        )}

      </div>
    </div>
  );
};
