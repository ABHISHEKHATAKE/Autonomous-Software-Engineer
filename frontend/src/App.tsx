import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ArrowRight, Bot, CheckCircle2, GitBranch, Lock, Play, Rocket, ServerCog, ShieldCheck, Sparkles, TerminalSquare, UserCircle2 } from 'lucide-react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';

type User = {
  id?: string;
  name: string;
  email: string;
};

type Task = {
  id: string;
  title: string;
  description: string;
  status: string;
  repository_id: string;
  priority: string;
  base_branch: string;
  current_agent: string;
  retry_count?: number;
  approval_status: string;
  feature_branch?: string | null;
  diff?: string | null;
  created_at: string;
  updated_at: string;
};

type DashboardSummary = {
  total_tasks: number;
  completed_tasks: number;
  in_progress_tasks: number;
  repositories: number;
  agent_status: string;
};

type GitHubRepo = {
  full_name: string;
  name: string;
  default_branch: string;
  primary_language: string;
  description: string;
};

type PhaseStatus = {
  phase: number;
  name: string;
  description: string;
  status: string;
  completed: boolean;
};

type WorkflowStep = {
  id: string;
  name: string;
  description: string;
  status: string;
  current: boolean;
};

type ExecutionResult = {
  task_id: string;
  command: string;
  exit_code: number;
  success: boolean;
  stdout: string;
  stderr: string;
  duration_ms: number;
  working_directory: string;
  created_at: string;
};

type PullRequest = {
  id: string;
  task_id: string;
  repository_id: string;
  title: string;
  head_branch: string;
  base_branch: string;
  status: string;
  body: string;
  url?: string | null;
  created_at: string;
};

type LLMConfiguration = {
  configured: boolean;
  provider: string;
  model: string;
};

type TaskEvent = {
  event: string;
  message: string;
  payload: Record<string, unknown>;
  timestamp: string;
};

type FailedPatchAttempt = {
  attempt: number;
  patch: string;
  error: string;
  generated_diff?: string;
  completion_metadata?: Array<{
    finish_reason?: string | null;
    usage?: Record<string, number>;
  }>;
};

function isFailedPatchAttempt(value: unknown): value is FailedPatchAttempt {
  if (typeof value !== 'object' || value === null) return false;
  const attempt = value as Record<string, unknown>;
  return typeof attempt.attempt === 'number'
    && typeof attempt.patch === 'string'
    && typeof attempt.error === 'string';
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

async function apiFetch<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers ?? {});
    if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  headers.set('Content-Type', 'application/json');

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body) as { detail?: string };
      message = parsed.detail || body;
    } catch {
      message = body;
    }
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('ase-token'));
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem('ase-user');
    return stored ? JSON.parse(stored) : null;
  });
  const [tasks, setTasks] = useState<Task[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [phases, setPhases] = useState<PhaseStatus[]>([]);

  useEffect(() => {
    if (token) {
      localStorage.setItem('ase-token', token);
    } else {
      localStorage.removeItem('ase-token');
    }
  }, [token]);

  useEffect(() => {
    if (user) {
      localStorage.setItem('ase-user', JSON.stringify(user));
    } else {
      localStorage.removeItem('ase-user');
    }
  }, [user]);

  const refreshDashboard = async () => {
    if (!token) return;
    try {
      const [dashboard, taskList, phaseReport] = await Promise.all([
        apiFetch<DashboardSummary>('/dashboard', {}, token),
        apiFetch<Task[]>('/tasks', {}, token),
        apiFetch<{ phases: PhaseStatus[] }>('/phases', {}, token),
      ]);
      setSummary(dashboard);
      setTasks(taskList);
      setPhases(phaseReport.phases);
    } catch (error) {
      console.error('Failed to load dashboard', error);
    }
  };

  useEffect(() => {
    void refreshDashboard();
  }, [token]);

  if (!token || !user) {
    return <LandingPage onLogin={(newToken, newUser) => { setToken(newToken); setUser(newUser); }} />;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-cyan-500/50 bg-cyan-500/10 p-2 text-cyan-300">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Autonomous Software Engineer</p>
              <h1 className="text-lg font-semibold text-white">Execution Control Center</h1>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-300">{user.email}</span>
            <button
              className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-cyan-400 hover:text-white"
              onClick={() => {
                setToken(null);
                setUser(null);
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <Routes>
          <Route path="/" element={<DashboardPage summary={summary} tasks={tasks} phases={phases} refresh={refreshDashboard} token={token} />} />
          <Route path="/tasks/new" element={<TaskCreatePage onCreated={refreshDashboard} token={token} />} />
          <Route path="/repositories" element={<RepositoriesPage token={token} />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage token={token} />} />
        </Routes>
      </main>
    </div>
  );
}

function LandingPage({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('demo@ase.dev');
  const [password, setPassword] = useState('password123');
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/${registering ? 'register' : 'login'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(registering ? { name, email, password } : { email, password }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body?.detail || 'Login failed');
      }
      onLogin(body.access_token, body.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6">
      <div className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900 p-8 shadow-2xl shadow-cyan-950/20">
        <div className="mb-8 flex items-center gap-3">
          <div className="rounded-xl border border-cyan-500/50 bg-cyan-500/10 p-3 text-cyan-300">
            <Bot className="h-7 w-7" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Autonomous Software Engineer</p>
            <h1 className="text-2xl font-semibold text-white">{registering ? 'Create account' : 'Sign in'}</h1>
          </div>
        </div>

        <div className="space-y-4">
          {registering && (
            <label className="block">
              <span className="mb-2 block text-sm text-slate-300">Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
            </label>
          )}
          <label className="block">
            <span className="mb-2 block text-sm text-slate-300">Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm text-slate-300">Password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
          </label>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button onClick={() => void submit()} className="w-full rounded-xl bg-cyan-500 px-4 py-3 font-medium text-slate-950 hover:bg-cyan-400">
            {registering ? 'Create account' : 'Access control center'}
          </button>
          <button type="button" onClick={() => { setRegistering(!registering); setError(''); }} className="w-full text-sm text-cyan-300 hover:text-cyan-200">
            {registering ? 'Already have an account? Sign in' : 'Create a new account'}
          </button>
        </div>
      </div>
    </div>
  );
}

function DashboardPage({ summary, tasks, phases, refresh, token }: { summary: DashboardSummary | null; tasks: Task[]; phases: PhaseStatus[]; refresh: () => Promise<void>; token?: string | null }) {
  const stats = useMemo(() => [
    { icon: <ServerCog className="h-5 w-5" />, label: 'Tasks', value: String(summary?.total_tasks ?? 0) },
    { icon: <ShieldCheck className="h-5 w-5" />, label: 'Completed', value: String(summary?.completed_tasks ?? 0) },
    { icon: <Play className="h-5 w-5" />, label: 'In progress', value: String(summary?.in_progress_tasks ?? 0) },
    { icon: <GitBranch className="h-5 w-5" />, label: 'Repositories', value: String(summary?.repositories ?? 0) },
  ], [summary]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Overview</p>
          <h2 className="mt-2 text-3xl font-semibold text-white">Autonomous Workflow Dashboard</h2>
        </div>
        <div className="flex gap-3">
          <Link to="/tasks/new" className="rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 hover:bg-cyan-400">Create task</Link>
          <Link to="/repositories" className="rounded-lg border border-slate-700 px-4 py-2 font-medium text-slate-200 hover:border-slate-500">Repositories</Link>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} icon={stat.icon} label={stat.label} value={stat.value} />
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.8fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xl font-semibold text-white">Current tasks</h3>
            <button onClick={() => void refresh()} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500">Refresh</button>
          </div>
          <div className="space-y-3">
            {tasks.length === 0 ? (
              <p className="text-slate-400">No tasks yet. Create one to begin.</p>
            ) : (
              tasks.map((task) => (
                <Link key={task.id} to={`/tasks/${task.id}`} className="block rounded-xl border border-slate-800 bg-slate-950 p-4 hover:border-cyan-500/50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-lg font-medium text-white">{task.title}</p>
                      <p className="mt-1 text-sm text-slate-400">{task.description}</p>
                    </div>
                    <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-cyan-300">{task.status}</span>
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
                    <span>{task.priority}</span>
                    <span>{task.current_agent}</span>
                    <span>{new Date(task.created_at).toLocaleDateString()}</span>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="text-xl font-semibold text-white">Roadmap</h3>
          <div className="mt-4 space-y-3">
            {phases.map((phase) => (
              <div key={phase.phase} className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Phase {phase.phase}</p>
                  <span className={`rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.12em] ${phase.completed ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/15 text-amber-300'}`}>
                    {phase.status}
                  </span>
                </div>
                <p className="mt-2 font-medium text-white">{phase.name}</p>
                <p className="mt-1 text-sm text-slate-400">{phase.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function TaskCreatePage({ onCreated, token }: { onCreated: () => void; token?: string | null }) {
  const [title, setTitle] = useState('Implement JWT authentication');
  const [description, setDescription] = useState('Implement the requested feature with focused tests and preserve existing behavior.');
  const [priority, setPriority] = useState('high');
  const [baseBranch, setBaseBranch] = useState('main');
  const [repositoryId, setRepositoryId] = useState('');
  const [repositories, setRepositories] = useState<Array<{ id: string; full_name: string; default_branch: string }>>([]);
  const [llm, setLlm] = useState<LLMConfiguration | null>(null);
  const [error, setError] = useState('');
  const [loadingRepositories, setLoadingRepositories] = useState(true);
  const navigate = useNavigate();

  const loadTaskConfiguration = async () => {
    if (!token) return;
    setLoadingRepositories(true);
    setError('');
    const [repositoryResult, llmResult] = await Promise.allSettled([
      apiFetch<Array<{ id: string; full_name: string; default_branch: string }>>('/repositories', {}, token),
      apiFetch<LLMConfiguration>('/llm/config', {}, token),
    ]);

    if (repositoryResult.status === 'fulfilled') {
      const repositoryList = repositoryResult.value;
      const selectedRepository = repositoryList.find((repo) => repo.id === repositoryId) ?? repositoryList[0];
      setRepositories(repositoryList);
      setRepositoryId(selectedRepository?.id ?? '');
      if (selectedRepository) setBaseBranch(selectedRepository.default_branch);
    } else {
      setError(repositoryResult.reason instanceof Error
        ? `Unable to load connected repositories: ${repositoryResult.reason.message}`
        : 'Unable to load connected repositories.');
    }

    if (llmResult.status === 'fulfilled') {
      setLlm(llmResult.value);
    } else {
      setLlm(null);
      const message = llmResult.reason instanceof Error && llmResult.reason.message === 'Not Found'
        ? 'Groq status endpoint was not found. Restart the backend from this project folder, then refresh this page.'
        : llmResult.reason instanceof Error
          ? `Unable to check Groq configuration: ${llmResult.reason.message}`
          : 'Unable to check Groq configuration.';
      setError((current) => [
        current,
        current.includes(message) ? '' : message,
      ].filter(Boolean).join(' '));
    }
    setLoadingRepositories(false);
  };

  useEffect(() => {
    void loadTaskConfiguration();
  }, [token]);

  const handleSubmit = async () => {
    if (!token) return;
    if (!repositoryId) {
      setError('Connect a GitHub repository before creating a task.');
      return;
    }
    if (!llm?.configured) {
      setError('Groq is not configured. Set GROQ_API_KEY on the backend, then refresh this page.');
      return;
    }
    try {
      const result = await apiFetch<{ id: string }>('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          repository_id: repositoryId,
          title,
          description,
          priority,
          base_branch: baseBranch,
        }),
      }, token);
      await apiFetch<{ status: string }>(`/tasks/${result.id}/start`, { method: 'POST' }, token);
      onCreated();
      navigate(`/tasks/${result.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Task creation failed');
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="mb-4 text-2xl font-semibold text-white">Create a task</h2>
      <div className="space-y-4">
        <label className="block">
          <span className="mb-2 block text-sm text-slate-300">Task title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
        </label>
        <label className="block">
          <span className="mb-2 block text-sm text-slate-300">Repository</span>
          <select value={repositoryId} onChange={(e) => {
            setRepositoryId(e.target.value);
            setBaseBranch(repositories.find((repo) => repo.id === e.target.value)?.default_branch ?? 'main');
          }} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none">
            <option value="">Select a connected repository</option>
            {repositories.map((repo) => <option key={repo.id} value={repo.id}>{repo.full_name}</option>)}
          </select>
        </label>
        <p className="text-sm text-slate-400">
          {llm ? (llm.configured ? `Groq model: ${llm.model}` : 'Groq is not configured on the backend.') : 'Checking Groq configuration…'}
        </p>
        {loadingRepositories && <p className="text-sm text-slate-400">Loading connected repositories…</p>}
        {!loadingRepositories && !repositories.length && (
          <div className="space-y-2">
            <p className="text-sm text-slate-400">No repositories are connected yet. On the repositories page, click <strong>Connect</strong> beside a GitHub repository. Indexing is optional for it to appear here.</p>
            <Link to="/repositories" className="inline-block text-sm text-cyan-300 hover:text-cyan-200">Go to repositories</Link>
          </div>
        )}
        {!loadingRepositories && <button type="button" onClick={() => void loadTaskConfiguration()} className="text-sm text-cyan-300 hover:text-cyan-200">Refresh repositories</button>}
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm text-slate-300">Priority</span>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-2 block text-sm text-slate-300">Base branch</span>
            <input value={baseBranch} onChange={(e) => setBaseBranch(e.target.value)} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
          </label>
        </div>
        <label className="block">
          <span className="mb-2 block text-sm text-slate-300">Task description</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={5} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none" />
        </label>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button disabled={!repositoryId || !llm?.configured} onClick={() => void handleSubmit()} className="rounded-xl bg-cyan-500 px-4 py-2 font-medium text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50">Create task</button>
      </div>
    </div>
  );
}

function RepositoriesPage({ token }: { token?: string | null }) {
  const [repos, setRepos] = useState<Array<{ id: string; full_name: string; primary_language: string; indexing_status: string }>>([]);
  const [githubRepos, setGithubRepos] = useState<GitHubRepo[]>([]);
  const [githubToken, setGithubToken] = useState('');
  const [tokenStatus, setTokenStatus] = useState('');
  const [indexingRepositoryId, setIndexingRepositoryId] = useState<string | null>(null);
  const [error, setError] = useState('');

  const refreshRepos = async () => {
    if (!token) return;
    try {
      const [connected, remote] = await Promise.all([
        apiFetch<Array<{ id: string; full_name: string; primary_language: string; indexing_status: string }>>('/repositories', {}, token),
        apiFetch<GitHubRepo[]>('/github/repositories', {}, token),
      ]);
      setRepos(connected);
      setGithubRepos(remote);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load repositories');
    }
  };

  useEffect(() => {
    void refreshRepos();
  }, [token]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('github') === 'connected') {
      setTokenStatus('GitHub OAuth connected successfully.');
      window.history.replaceState({}, '', window.location.pathname);
      void refreshRepos();
    }
  }, [token]);

  const connectRepo = async (repo: GitHubRepo) => {
    if (!token) return;
    try {
      await apiFetch<{ id: string; full_name: string; primary_language: string; indexing_status: string }>('/repositories', {
        method: 'POST',
        body: JSON.stringify({
          full_name: repo.full_name,
          name: repo.name,
          default_branch: repo.default_branch,
          primary_language: repo.primary_language,
        }),
      }, token);
      await refreshRepos();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to connect repository');
    }
  };

  const indexRepo = async (repositoryId: string) => {
    if (!token) return;
    setIndexingRepositoryId(repositoryId);
    setError('');
    try {
      const result = await apiFetch<{ message: string }>(`/repositories/${repositoryId}/index`, { method: 'POST' }, token);
      setTokenStatus(result.message);
      await refreshRepos();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Repository indexing failed');
    } finally {
      setIndexingRepositoryId(null);
    }
  };

  const saveGithubToken = async () => {
    if (!token || !githubToken.trim()) return;
    try {
      await apiFetch<{ status: string }>('/github/token', {
        method: 'POST',
        body: JSON.stringify({ token: githubToken.trim() }),
      }, token);
      setGithubToken('');
      setTokenStatus('GitHub account verified and credential encrypted.');
      await refreshRepos();
    } catch (error) {
      setTokenStatus(error instanceof Error ? error.message : 'Unable to configure GitHub token');
    }
  };

  const connectWithOAuth = async () => {
    if (!token) return;
    try {
      const result = await apiFetch<{ url: string }>('/github/oauth/url', {}, token);
      window.location.assign(result.url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to start GitHub OAuth');
    }
  };

  return (
    <div className="space-y-6 rounded-2xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold text-white">Connected repositories</h2>
        <button onClick={() => void refreshRepos()} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500">Refresh</button>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
        <h3 className="mb-3 text-lg font-medium text-white">GitHub access</h3>
        <div className="flex flex-col gap-3 md:flex-row">
          <input
            type="password"
            value={githubToken}
            onChange={(e) => setGithubToken(e.target.value)}
            placeholder="ghp_xxx or github_pat_xxx"
            className="flex-1 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none"
          />
          <button onClick={() => void saveGithubToken()} className="rounded-xl bg-cyan-500 px-4 py-2 font-medium text-slate-950 hover:bg-cyan-400">Save token</button>
          <button onClick={() => void connectWithOAuth()} className="rounded-xl border border-slate-700 px-4 py-2 font-medium text-slate-200 hover:border-cyan-400">Connect with OAuth</button>
        </div>
        {tokenStatus && <p className="mt-3 text-sm text-cyan-300">{tokenStatus}</p>}
        {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
      </div>

      <div className="space-y-3">
        {repos.map((repo) => (
          <div key={repo.id} className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-medium text-white">{repo.full_name}</p>
              <div className="flex items-center gap-3">
                <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-xs uppercase tracking-[0.18em] text-cyan-300">{repo.indexing_status}</span>
                <button
                  type="button"
                  disabled={indexingRepositoryId === repo.id}
                  onClick={() => void indexRepo(repo.id)}
                  className="rounded-lg border border-cyan-500/50 px-3 py-1.5 text-sm font-medium text-cyan-300 hover:bg-cyan-500/10 disabled:cursor-wait disabled:opacity-60"
                >
                  {indexingRepositoryId === repo.id ? 'Indexing…' : 'Index'}
                </button>
              </div>
            </div>
            <p className="mt-2 text-sm text-slate-400">Primary language: {repo.primary_language}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
        <h3 className="mb-3 text-lg font-medium text-white">Available GitHub repositories</h3>
        <div className="space-y-3">
          {githubRepos.map((repo) => (
            <div key={repo.full_name} className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900 p-3">
              <div>
                <p className="font-medium text-white">{repo.full_name}</p>
                <p className="text-sm text-slate-400">{repo.description}</p>
              </div>
              <button onClick={() => void connectRepo(repo)} className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400">Connect</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TaskDetailPage({ token }: { token?: string | null }) {
  const { taskId } = useParams();
  const [task, setTask] = useState<Task | null>(null);
  const [diff, setDiff] = useState<string>('');
  const [workflow, setWorkflow] = useState<WorkflowStep[]>([]);
  const [execution, setExecution] = useState<ExecutionResult | null>(null);
  const [pullRequest, setPullRequest] = useState<PullRequest | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [validationCommand, setValidationCommand] = useState('');
  const [error, setError] = useState('');

  const refreshTask = async () => {
    if (!token || !taskId) return;
    try {
      const [data, diffResponse, workflowResponse, logResponse] = await Promise.all([
        apiFetch<Task>(`/tasks/${taskId}`, {}, token),
        apiFetch<{ diff: string }>(`/tasks/${taskId}/diff`, {}, token),
        apiFetch<{ task_id: string; status: string; current_agent: string; steps: WorkflowStep[] }>(`/tasks/${taskId}/workflow`, {}, token),
        apiFetch<{ task_id: string; events: TaskEvent[] }>(`/tasks/${taskId}/logs`, {}, token),
      ]);
      setTask(data);
      setDiff(diffResponse.diff);
      setWorkflow(workflowResponse.steps);
      setEvents(logResponse.events);
      const prList = await apiFetch<PullRequest[]>(`/repositories/${data.repository_id}/pull-requests`, {}, token);
      setPullRequest(prList.find((pr) => pr.task_id === data.id) ?? null);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load task');
    }
  };

  useEffect(() => {
    void refreshTask();
  }, [token, taskId]);

  const runWorkflow = async () => {
    if (!token || !taskId) return;
    try {
      await apiFetch<{ status: string; current_agent: string }>(`/tasks/${taskId}/workflow/run`, { method: 'POST' }, token);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Workflow stage failed');
      await refreshTask();
    }
  };

  const runValidation = async () => {
    if (!token || !taskId) return;
    try {
      const result = await apiFetch<ExecutionResult>(`/tasks/${taskId}/execute`, {
        method: 'POST',
        body: JSON.stringify({ command: validationCommand.trim() || undefined, timeout_seconds: 120 }),
      }, token);
      setExecution(result);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed');
    }
  };

  const skipValidation = async () => {
    if (!token || !taskId) return;
    if (!window.confirm('Skip sandbox validation? Tests will not run, and the task will be marked as unvalidated before review.')) return;
    try {
      await apiFetch(`/tasks/${taskId}/skip-validation`, { method: 'POST' }, token);
      setExecution(null);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to skip validation');
    }
  };

  const approve = async () => {
    if (!token || !taskId) return;
    try {
      await apiFetch<{ status: string }>(`/tasks/${taskId}/approve`, { method: 'POST' }, token);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval failed');
    }
  };

  const reject = async () => {
    if (!token || !taskId) return;
    try {
      await apiFetch<{ status: string }>(`/tasks/${taskId}/reject`, { method: 'POST' }, token);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rejection failed');
    }
  };

  const cancel = async () => {
    if (!token || !taskId) return;
    try {
      await apiFetch(`/tasks/${taskId}/cancel`, { method: 'POST' }, token);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to cancel task');
    }
  };

  const retry = async () => {
    if (!token || !taskId) return;
    try {
      await apiFetch(`/tasks/${taskId}/retry`, { method: 'POST' }, token);
      await apiFetch(`/tasks/${taskId}/start`, { method: 'POST' }, token);
      setExecution(null);
      await refreshTask();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to retry task');
    }
  };

  const reviewerCompleted = events.some((event) => (
    event.event === 'agent_completed' && event.payload.agent === 'reviewer'
  ));

  const createPr = async () => {
    if (!token || !taskId) return;
    try {
      const result = await apiFetch<PullRequest>(`/tasks/${taskId}/pull-request`, {
        method: 'POST',
        body: JSON.stringify({
          title: task?.title ?? 'Autonomous patch',
          head_branch: task?.feature_branch ?? undefined,
          base_branch: task?.base_branch ?? 'main',
          body: `## Summary\n\n${task?.description ?? 'Autonomous task created.'}`,
        }),
      }, token);
      setPullRequest(result);
      await refreshTask();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to create draft pull request');
    }
  };

  if (!task) {
    return <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 text-slate-300">{error || 'Loading task…'}</div>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Task detail</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">{task.title}</h2>
          </div>
          <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-3 py-1 text-xs uppercase tracking-[0.16em] text-cyan-300">{task.status}</span>
        </div>
        <p className="text-slate-300">{task.description}</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3 text-sm text-slate-300">
          <Pill value={`Priority: ${task.priority}`} />
          <Pill value={`Branch: ${task.base_branch}`} />
          <Pill value={`Agent: ${task.current_agent}`} />
        </div>
        <p className="mt-3 text-xs text-slate-400">Feature branch: {task.feature_branch ?? 'assigned after task creation'}</p>
        <div className="mt-4 flex gap-3">
          {!['completed', 'failed', 'cancelled'].includes(task.status) && (
            <button onClick={() => void cancel()} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-rose-400 hover:text-rose-200">Cancel task</button>
          )}
          {['failed', 'cancelled'].includes(task.status) && (
            <button onClick={() => void retry()} className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200 hover:bg-cyan-500/20">Retry task</button>
          )}
        </div>
      </div>
      {error && <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-xl font-semibold text-white">Workflow</h3>
            <button disabled={task.status === 'failed' || task.status === 'completed' || task.current_agent === 'validator' || reviewerCompleted} onClick={() => void runWorkflow()} className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50">
              {reviewerCompleted ? 'Reviewer complete' : task.current_agent === 'reviewer' ? 'Run reviewer' : 'Run agent stage'}
            </button>
          </div>
          <div className="space-y-3">
            {workflow.map((step) => (
              <div key={step.id} className={`rounded-xl border p-3 ${step.current ? 'border-cyan-500/50 bg-cyan-500/10' : 'border-slate-800 bg-slate-950'}`}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">{step.name}</p>
                    <p className="text-sm text-slate-400">{step.description}</p>
                  </div>
                  <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">{step.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="mb-4 text-xl font-semibold text-white">Validation</h3>
          <label className="mb-3 block">
            <span className="mb-2 block text-sm text-slate-400">Command (optional)</span>
            <input value={validationCommand} onChange={(event) => setValidationCommand(event.target.value)} placeholder="Use repository default, or e.g. python -m pytest -q" className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none" />
          </label>
          <button disabled={!diff || task.current_agent !== 'validator'} onClick={() => void runValidation()} className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-3 font-medium text-slate-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50">
            <TerminalSquare className="h-5 w-5" />
            Run sandbox validation
          </button>
          {diff && task.current_agent === 'validator' && ['testing', 'failed'].includes(task.status) && (
            <button type="button" onClick={() => void skipValidation()} className="mb-4 w-full rounded-xl border border-amber-500/50 px-4 py-3 text-sm font-medium text-amber-200 hover:bg-amber-500/10">
              Skip validation (tests will not run)
            </button>
          )}
          {events.some((event) => (
            event.event === 'validation_skipped'
            && event.payload.skipped === true
            && event.payload.retry_count === (task.retry_count ?? 0)
          )) && (
            <p className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
              Validation skipped. Automated tests were not run; review the patch carefully.
            </p>
          )}
          {execution ? (
            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-white">Exit code: {execution.exit_code}</span>
                <span className={`rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.12em] ${execution.success ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>
                  {execution.success ? 'pass' : 'fail'}
                </span>
              </div>
              <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-900 p-3 text-xs text-cyan-100">{execution.stdout || execution.stderr || 'No output returned.'}</pre>
            </div>
          ) : (
            <p className="text-sm text-slate-400">No validation run yet.</p>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
        <h3 className="mb-4 text-xl font-semibold text-white">Agent and validation output</h3>
        <div className="space-y-3">
          {events.filter((event) => event.event === 'agent_completed' || event.event === 'agent_failed' || event.event.startsWith('validation_')).length === 0 ? (
            <p className="text-sm text-slate-400">Agent results and validation logs will appear here.</p>
          ) : events.filter((event) => event.event === 'agent_completed' || event.event === 'agent_failed' || event.event.startsWith('validation_')).map((event, index) => (
            <details key={`${event.timestamp}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950 p-4" open={event.event === 'agent_completed' && event.payload.agent === 'reviewer'}>
              <summary className="cursor-pointer font-medium text-white">{String(event.payload.agent ?? event.message)} · {event.event}</summary>
              <p className={`mt-3 text-sm ${event.event === 'agent_failed' ? 'text-rose-300' : 'text-slate-400'}`}>{event.message}</p>
              {typeof event.payload.model_output === 'string' && (
                <details className="mt-3 rounded-lg border border-slate-800 p-3">
                  <summary className="cursor-pointer text-sm text-cyan-200">Groq structured file edits</summary>
                  <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-slate-300">{event.payload.model_output}</pre>
                  <p className="mt-2 text-xs text-slate-400">Completion: {JSON.stringify(event.payload.completion_metadata ?? [])}</p>
                </details>
              )}
              {Array.isArray(event.payload.patch_attempts) && event.payload.patch_attempts.map((attempt, attemptIndex) => (
                isFailedPatchAttempt(attempt) && (
                  <details key={`${attempt.attempt}-${attemptIndex}`} className="mt-3 rounded-lg border border-slate-800 p-3">
                    <summary className="cursor-pointer text-sm text-amber-200">Groq output · attempt {attempt.attempt}</summary>
                    <p className="mt-2 text-xs text-rose-300">
                      {attempt.error || (attempt.generated_diff ? 'Structured edits applied; Git generated this diff.' : 'No validation message recorded.')}
                    </p>
                    {attempt.completion_metadata && (
                      <p className="mt-2 text-xs text-slate-400">
                        Completion: {JSON.stringify(attempt.completion_metadata)}
                      </p>
                    )}
                    <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-slate-300">{attempt.patch}</pre>
                    {attempt.generated_diff && (
                      <>
                        <p className="mt-3 text-xs font-medium text-slate-400">Git-generated diff</p>
                        <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-cyan-100">{attempt.generated_diff}</pre>
                      </>
                    )}
                  </details>
                )
              ))}
              {typeof event.payload.result === 'string' && !Array.isArray(event.payload.patch_attempts) && (
                <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-xs text-slate-300">{event.payload.result}</pre>
              )}
            </details>
          ))}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="mb-4 text-xl font-semibold text-white">Diff preview</h3>
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-cyan-100">{diff || 'No diff yet.'}</pre>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="mb-4 text-xl font-semibold text-white">Approval actions</h3>
          <div className="space-y-3">
            <button disabled={task.status !== 'reviewing' || task.current_agent !== 'reviewer' || !reviewerCompleted} onClick={() => void approve()} className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-3 font-medium text-slate-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50">
              <CheckCircle2 className="h-5 w-5" />
              Approve task
            </button>
            <button disabled={task.approval_status !== 'approved' || Boolean(pullRequest)} onClick={() => void createPr()} className="flex w-full items-center justify-center gap-2 rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-3 font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50">
              <GitBranch className="h-5 w-5" />
              {pullRequest ? 'Refresh PR' : 'Create PR'}
            </button>
            <button disabled={task.status !== 'reviewing'} onClick={() => void reject()} className="flex w-full items-center justify-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 font-medium text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">
              <Lock className="h-5 w-5" />
              Reject task
            </button>
          </div>
          {pullRequest && (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950 p-3">
              <p className="text-sm font-medium text-white">{pullRequest.title}</p>
              <p className="mt-1 text-xs text-slate-400">{pullRequest.head_branch} → {pullRequest.base_branch}</p>
              {pullRequest.url && <a href={pullRequest.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-cyan-300">Open PR</a>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Pill({ value }: { value: string }) {
  return <span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-xs uppercase tracking-[0.18em] text-slate-300">{value}</span>;
}

function StatCard({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-300">{icon}</div>
      <p className="text-sm text-slate-400">{label}</p>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
    </div>
  );
}

export default App;
