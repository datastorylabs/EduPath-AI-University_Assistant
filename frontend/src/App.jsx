import { useEffect, useMemo, useState } from "react";
import { ApiError, apiRequest, bootstrapCsrf, safeHttpUrl } from "./api.js";

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "profile", label: "My profile", icon: "user" },
  { id: "eligibility", label: "Program finder", icon: "search" },
  { id: "advisor", label: "Guided advisor", icon: "messages" },
];

const EMPTY_DRAFT = {
  qualification: "",
  ssc_percent: "",
  hssc_percent: "",
  subjects: "",
  subject_percentages: "",
  equivalency_status: "unknown",
};

const QUALIFICATION_HINT = "ICS, FSc Pre-Engineering, FSc Pre-Medical, A Levels, or Equivalent";

function Icon({ name, size = 18 }) {
  const paths = {
    home: ["M3 10.8 12 3l9 7.8", "M5.5 9.5V21h13V9.5", "M9.5 21v-7h5v7"],
    user: ["M20 21a8 8 0 0 0-16 0", "M12 13a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z"],
    search: ["m20 20-4.2-4.2", "M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z"],
    messages: ["M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"],
    arrow: ["M5 12h14", "m12 5 7 7-7 7"],
    check: ["m5 12 4 4L19 6"],
    plus: ["M12 5v14", "M5 12h14"],
    lock: ["M5 10V7a7 7 0 0 1 14 0v3", "M4 10h16v11H4z", "M12 14v3"],
    external: ["M14 3h7v7", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
    logout: ["M10 17l5-5-5-5", "M15 12H3", "M12 3h6a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3h-6"],
    book: ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20", "M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"],
    shield: ["M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z", "m9 12 2 2 4-4"],
    trash: ["M3 6h18", "M8 6V4h8v2", "m19 6-1 15H6L5 6", "M10 11v5", "M14 11v5"],
    refresh: ["M20 7v5h-5", "M4 17v-5h5", "M5.6 9a7 7 0 0 1 11.6-2L20 12", "M4 12l2.8 5a7 7 0 0 0 11.6-2"],
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {(paths[name] || paths.book).map((path) => (
        <path d={path} key={path} />
      ))}
    </svg>
  );
}

function humanize(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return new Intl.DateTimeFormat("en-PK", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function makeDraft(profile) {
  if (!profile) return { ...EMPTY_DRAFT };
  const marks = Object.entries(profile.subject_percentages || {})
    .map(([subject, mark]) => subject + ": " + mark)
    .join(", ");
  return {
    qualification: profile.qualification || "",
    ssc_percent: profile.ssc_percent ?? "",
    hssc_percent: profile.hssc_percent ?? "",
    subjects: (profile.subjects || []).join(", "),
    subject_percentages: marks,
    equivalency_status: profile.equivalency_status || "unknown",
  };
}

function parseSubjectMarks(input) {
  const output = {};
  const value = String(input || "").trim();
  if (!value) return output;

  for (const item of value.split(",")) {
    const separator = item.lastIndexOf(":");
    if (separator < 1) {
      throw new Error("Enter subject marks like Mathematics: 85, Physics: 78.");
    }
    const subject = item.slice(0, separator).trim();
    const markText = item.slice(separator + 1).trim();
    const mark = Number(markText);
    if (!subject || !Number.isFinite(mark) || mark < 0 || mark > 100) {
      throw new Error("Subject marks must use a subject name and a percentage from 0 to 100.");
    }
    output[subject] = mark;
  }
  return output;
}

function profileProgress(profile) {
  if (!profile) return 0;
  const checks = [
    Boolean(profile.qualification),
    profile.ssc_percent !== null && profile.ssc_percent !== undefined,
    profile.hssc_percent !== null && profile.hssc_percent !== undefined,
    Array.isArray(profile.subjects) && profile.subjects.length > 0,
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

function statusLabel(status) {
  const labels = {
    eligible: "Meets listed minimums",
    conditionally_eligible: "Conditional pathway",
    ineligible: "Below a listed minimum",
    indeterminate: "More information needed",
  };
  return labels[status] || humanize(status);
}

function parseProgramCheck(message) {
  if (!message || message.role !== "assistant") return null;
  try {
    const payload = JSON.parse(message.content);
    if (payload && payload.type === "profile_program_check" && Array.isArray(payload.results)) {
      return payload;
    }
  } catch {
    return null;
  }
  return null;
}

function StatusPill({ status }) {
  return <span className={"status-pill status-" + String(status || "unknown")}>{statusLabel(status)}</span>;
}

function SourceLinks({ sources = [] }) {
  const safeSources = sources
    .map((source) => ({ ...source, safeUrl: safeHttpUrl(source.url) }))
    .filter((source) => source.safeUrl);
  if (!safeSources.length) {
    return <span className="muted-text small-text">No verified source link attached to this result.</span>;
  }
  return (
    <div className="source-links">
      {safeSources.map((source) => (
        <a
          key={source.safeUrl}
          href={source.safeUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="source-link"
        >
          <span>{source.title || "Official source"}</span>
          <Icon name="external" size={13} />
        </a>
      ))}
    </div>
  );
}

function RequirementList({ checks = [] }) {
  if (!checks.length) return <p className="muted-text small-text">No individual checks were returned.</p>;
  return (
    <div className="requirement-list">
      {checks.map((check, index) => (
        <div className="requirement-row" key={String(check.requirement) + "-" + index}>
          <span className={"requirement-dot requirement-" + String(check.status || "unknown")} aria-hidden="true" />
          <div>
            <strong>{humanize(check.requirement)}</strong>
            <p>{check.explanation}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function ProgramResultCard({ result, showChecks = false }) {
  return (
    <article className="program-result-card">
      <div className="program-result-topline">
        <span className="university-label">{result.university_name || humanize(result.university_id)}</span>
        <span className="cycle-label">Cycle {result.cycle}</span>
      </div>
      <div className="program-result-title-row">
        <div>
          <h4>{result.program_name || humanize(result.program_id)}</h4>
          <p className="muted-text small-text">Rule version {result.rule_version || "source record"}</p>
        </div>
        <StatusPill status={result.status} />
      </div>
      {result.note ? <p className="program-note">{result.note}</p> : null}
      {showChecks ? <RequirementList checks={result.checks || []} /> : null}
      <SourceLinks sources={result.sources || result.source_details || []} />
    </article>
  );
}

function ProgramCheckMessage({ payload }) {
  if (!payload) return null;
  const counts = payload.counts || {};
  const results = payload.results || [];
  return (
    <div className="program-check-message">
      <p className="assistant-summary">{payload.summary || "Your profile review is ready."}</p>
      <div className="check-counts">
        <div><strong>{counts.eligible ?? 0}</strong><span>Meets minimums</span></div>
        <div><strong>{counts.conditionally_eligible ?? 0}</strong><span>Conditional</span></div>
        <div><strong>{counts.ineligible ?? 0}</strong><span>Below minimum</span></div>
        <div><strong>{counts.indeterminate ?? 0}</strong><span>Need more info</span></div>
      </div>
      <div className="result-stack">
        {results.map((result) => (
          <ProgramResultCard
            key={result.university_id + "-" + result.program_id + "-" + result.cycle}
            result={result}
            showChecks
          />
        ))}
      </div>
      <p className="notice-text">{payload.notice}</p>
    </div>
  );
}

function AuthScreen({ onSubmit, busy, error, onClearError, apiUnavailable }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setLocalError("");
    onClearError();
    if (mode === "register" && password !== confirmPassword) {
      setLocalError("The passwords do not match.");
      return;
    }
    await onSubmit({ mode, email: email.trim(), password });
  };

  return (
    <div className="auth-layout">
      <section className="auth-story">
        <div className="brand-lockup">
          <span className="brand-mark">EP</span>
          <span className="brand-word">EduPath<span className="brand-period">.</span></span>
        </div>
        <div className="auth-story-copy">
          <span className="eyebrow">YOUR NEXT CHAPTER, MADE CLEARER</span>
          <h1>Make university choices with <em>confidence.</em></h1>
          <p>Understand the rules, keep your academic profile in one place, and see how your results line up with currently verified programmes.</p>
        </div>
        <div className="auth-story-foot">
          <span className="mini-shield"><Icon name="shield" size={16} /></span>
          <div><strong>Private by design</strong><p>Secure sessions. Your profile stays tied to your account.</p></div>
        </div>
        <div className="auth-decoration auth-decoration-one" />
        <div className="auth-decoration auth-decoration-two" />
      </section>

      <section className="auth-panel">
        <div className="auth-form-wrap">
          <div className="mobile-brand brand-lockup">
            <span className="brand-mark">EP</span>
            <span className="brand-word">EduPath<span className="brand-period">.</span></span>
          </div>
          <p className="eyebrow auth-eyebrow">ADMISSIONS WORKSPACE</p>
          <h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2>
          <p className="auth-intro">{mode === "login" ? "Sign in to continue your admissions journey." : "Start with an account to save your profile and eligibility checks."}</p>

          {apiUnavailable ? (
            <div className="inline-warning" role="status">
              <strong>API connection not ready</strong>
              <span>Start the backend and refresh this page before signing in.</span>
            </div>
          ) : null}
          {(localError || error) ? (
            <div className="alert alert-error" role="alert">{localError || error}</div>
          ) : null}

          <form className="auth-form" onSubmit={submit}>
            <label className="field-label" htmlFor="auth-email">Email address</label>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              maxLength={320}
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />

            <label className="field-label" htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder={mode === "login" ? "Your password" : "At least 12 characters"}
              minLength={mode === "register" ? 12 : 1}
              maxLength={128}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />

            {mode === "register" ? (
              <>
                <label className="field-label" htmlFor="auth-confirm-password">Confirm password</label>
                <input
                  id="auth-confirm-password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Re-enter your password"
                  minLength={12}
                  maxLength={128}
                  required
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
                <p className="field-help">Use 12 or more characters. Never reuse a password you use elsewhere.</p>
              </>
            ) : null}

            <button className="button button-primary auth-submit" type="submit" disabled={busy || apiUnavailable}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in to EduPath" : "Create secure account"}
              {!busy ? <Icon name="arrow" size={17} /> : null}
            </button>
          </form>

          <p className="auth-switch">
            {mode === "login" ? "New to EduPath?" : "Already have an account?"}{" "}
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setLocalError("");
                onClearError();
              }}
            >
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
          <div className="auth-legal"><Icon name="lock" size={14} /><span>Personal data is sent only to your configured EduPath API.</span></div>
        </div>
      </section>
    </div>
  );
}

function ProfileFields({ draft, onChange }) {
  const set = (key) => (event) => onChange({ ...draft, [key]: event.target.value });
  return (
    <div className="profile-form-grid">
      <div className="form-field form-field-full">
        <label htmlFor="qualification">Current qualification</label>
        <input
          id="qualification"
          value={draft.qualification}
          onChange={set("qualification")}
          placeholder={QUALIFICATION_HINT}
          maxLength={120}
          required
        />
        <span className="field-help">Use the qualification wording that best matches your certificate.</span>
      </div>
      <div className="form-field">
        <label htmlFor="ssc-percent">SSC / Matric percentage</label>
        <div className="input-with-suffix">
          <input
            id="ssc-percent"
            type="number"
            min="0"
            max="100"
            step="0.01"
            inputMode="decimal"
            value={draft.ssc_percent}
            onChange={set("ssc_percent")}
            placeholder="e.g. 86.5"
            required
          />
          <span>%</span>
        </div>
      </div>
      <div className="form-field">
        <label htmlFor="hssc-percent">HSSC / Intermediate percentage</label>
        <div className="input-with-suffix">
          <input
            id="hssc-percent"
            type="number"
            min="0"
            max="100"
            step="0.01"
            inputMode="decimal"
            value={draft.hssc_percent}
            onChange={set("hssc_percent")}
            placeholder="e.g. 79"
            required
          />
          <span>%</span>
        </div>
      </div>
      <div className="form-field form-field-full">
        <label htmlFor="subjects">Subjects studied</label>
        <input
          id="subjects"
          value={draft.subjects}
          onChange={set("subjects")}
          placeholder="Mathematics, Physics, Computer Science"
          maxLength={800}
          required
        />
        <span className="field-help">Separate subjects with commas. Use names such as Mathematics, Physics, Chemistry, Biology, or Computer Science.</span>
      </div>
      <div className="form-field form-field-full">
        <label htmlFor="subject-marks">Subject percentages <span className="optional-label">Optional</span></label>
        <input
          id="subject-marks"
          value={draft.subject_percentages}
          onChange={set("subject_percentages")}
          placeholder="Mathematics: 88, Physics: 81"
          maxLength={1200}
        />
        <span className="field-help">Enter only if you know the marks. Use “Subject: percentage” pairs separated by commas.</span>
      </div>
      <div className="form-field form-field-full">
        <label htmlFor="equivalency">IBCC equivalency status</label>
        <select id="equivalency" value={draft.equivalency_status} onChange={set("equivalency_status")} required>
          <option value="unknown">Not sure yet</option>
          <option value="confirmed">Confirmed</option>
          <option value="pending">In progress</option>
          <option value="not_required">Not required for my qualification</option>
          <option value="not_applicable">Not applicable</option>
        </select>
        <span className="field-help">Foreign qualifications may require IBCC equivalency for a university's eligibility process.</span>
      </div>
    </div>
  );
}

function ProfilePage({ profile, draft, setDraft, onSave, onDelete, busy, onNavigate }) {
  const progress = profileProgress(profile);
  const level = progress >= 100 ? "progress-100" : progress >= 75 ? "progress-75" : progress >= 50 ? "progress-50" : progress >= 25 ? "progress-25" : "progress-0";
  return (
    <div className="page-stack">
      <section className="page-intro">
        <div>
          <span className="eyebrow">YOUR ACADEMIC RECORD</span>
          <h2>My student profile</h2>
          <p>Save your marks and subjects once. EduPath uses this record for its rules-based programme checks.</p>
        </div>
        <span className="private-tag"><Icon name="lock" size={14} /> Private to your account</span>
      </section>

      <div className="profile-layout">
        <section className="panel profile-editor">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">ACADEMIC DETAILS</span>
              <h3>{profile ? "Update your profile" : "Build your profile"}</h3>
            </div>
            <span className="panel-step">01 / 02</span>
          </div>
          <form onSubmit={onSave}>
            <ProfileFields draft={draft} onChange={setDraft} />
            <div className="form-actions">
              <button className="button button-primary" type="submit" disabled={busy}>
                {busy ? "Saving…" : profile ? "Save changes" : "Save profile"}
                {!busy ? <Icon name="check" size={16} /> : null}
              </button>
              {profile ? (
                <button className="button button-quiet button-danger" type="button" onClick={onDelete} disabled={busy}>
                  <Icon name="trash" size={15} /> Delete profile
                </button>
              ) : null}
            </div>
          </form>
        </section>

        <aside className="profile-side">
          <section className="panel progress-panel">
            <div className="panel-heading">
              <div><span className="section-kicker">PROFILE READINESS</span><h3>{progress}% complete</h3></div>
              <div className="progress-orbit">{progress === 100 ? <Icon name="check" size={21} /> : <span>{progress}%</span>}</div>
            </div>
            <div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completion">
              <div className={"progress-fill " + level} />
            </div>
            <div className="progress-checklist">
              <div className={profile?.qualification ? "done" : ""}><span>{profile?.qualification ? "✓" : "1"}</span> Qualification</div>
              <div className={profile?.ssc_percent !== null && profile?.ssc_percent !== undefined ? "done" : ""}><span>{profile?.ssc_percent !== null && profile?.ssc_percent !== undefined ? "✓" : "2"}</span> SSC marks</div>
              <div className={profile?.hssc_percent !== null && profile?.hssc_percent !== undefined ? "done" : ""}><span>{profile?.hssc_percent !== null && profile?.hssc_percent !== undefined ? "✓" : "3"}</span> HSSC marks</div>
              <div className={profile?.subjects?.length ? "done" : ""}><span>{profile?.subjects?.length ? "✓" : "4"}</span> Subject list</div>
            </div>
            <p className="panel-footnote">You can save an incomplete profile, but missing information may lead to an “indeterminate” result.</p>
          </section>
          <section className="tip-panel">
            <div className="tip-icon"><Icon name="shield" size={19} /></div>
            <div><h4>Use accurate details</h4><p>This profile is for planning. Check your official marks sheet and the university’s current criteria before applying.</p></div>
          </section>
          <button className="button button-secondary full-button" onClick={() => onNavigate("eligibility")} type="button">
            Go to program finder <Icon name="arrow" size={16} />
          </button>
        </aside>
      </div>
    </div>
  );
}

function OverviewPage({ user, profile, catalog, rules, universities, conversations, onNavigate }) {
  const progress = profileProgress(profile);
  const availableRules = rules.filter((rule) => rule.evaluation_available);
  const firstName = String(user?.email || "student").split("@")[0].split(/[._-]/)[0] || "student";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div className="hero-content">
          <span className="hero-eyebrow"><span className="hero-eyebrow-dot" /> PAKISTAN UNIVERSITY ADMISSIONS</span>
          <h2>{greeting}, {firstName}.</h2>
          <h3>Let’s make your next step <em>clearer.</em></h3>
          <p>Keep your academic details ready, explore source-backed eligibility rules, and understand what needs checking before you apply.</p>
          <div className="hero-actions">
            <button className="button button-light" onClick={() => onNavigate(profile ? "eligibility" : "profile")} type="button">
              {profile ? "Check program fit" : "Complete your profile"} <Icon name="arrow" size={16} />
            </button>
            <button className="button button-glass" onClick={() => onNavigate("advisor")} type="button">Open guided advisor</button>
          </div>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="orbit orbit-large" />
          <div className="orbit orbit-small" />
          <div className="hero-visual-card hero-visual-card-top"><span className="visual-mini-icon">✓</span><span><b>Know the criteria</b><small>Verified rules first</small></span></div>
          <div className="hero-visual-card hero-visual-card-bottom"><span className="visual-progress"><i /></span><span><b>Your profile</b><small>{progress}% ready to check</small></span></div>
          <div className="hero-dot hero-dot-one" />
          <div className="hero-dot hero-dot-two" />
        </div>
      </section>

      <section className="stat-grid" aria-label="Workspace summary">
        <div className="stat-card"><div className="stat-top"><span>Rules ready to evaluate</span><span className="stat-icon stat-icon-teal"><Icon name="check" size={17} /></span></div><strong>{catalog?.evaluable_rule_count ?? availableRules.length}</strong><p>Selected, source-verified programme rules</p></div>
        <div className="stat-card"><div className="stat-top"><span>Universities tracked</span><span className="stat-icon stat-icon-blue"><Icon name="book" size={17} /></span></div><strong>{catalog?.university_count ?? universities.length}</strong><p>Coverage varies by campus and intake</p></div>
        <div className="stat-card"><div className="stat-top"><span>Profile readiness</span><span className="stat-icon stat-icon-violet"><Icon name="user" size={17} /></span></div><strong>{progress}%</strong><p>{profile ? "Your saved academic profile" : "No profile saved yet"}</p></div>
        <div className="stat-card"><div className="stat-top"><span>Saved sessions</span><span className="stat-icon stat-icon-amber"><Icon name="messages" size={17} /></span></div><strong>{conversations.length}</strong><p>Private to your signed-in account</p></div>
      </section>

      <section className="overview-lower">
        <div className="panel overview-main-panel">
          <div className="panel-heading panel-heading-spaced">
            <div><span className="section-kicker">YOUR WORKSPACE</span><h3>Pick up where you left off</h3></div>
            <span className="muted-text small-text">Personalised to your profile</span>
          </div>
          <div className="next-step-list">
            <button className="next-step-row" onClick={() => onNavigate("profile")} type="button">
              <span className={"next-step-icon " + (profile ? "step-done" : "")}><Icon name={profile ? "check" : "user"} size={18} /></span>
              <span className="next-step-copy"><strong>{profile ? "Review your student profile" : "Add your academic details"}</strong><small>{profile ? "Update marks, subjects, or equivalency status." : "Marks and subjects are needed for useful checks."}</small></span>
              <Icon name="arrow" size={16} />
            </button>
            <button className="next-step-row" onClick={() => onNavigate("eligibility")} type="button">
              <span className="next-step-icon"><Icon name="search" size={18} /></span>
              <span className="next-step-copy"><strong>Explore programme criteria</strong><small>Compare your saved details with available verified rules.</small></span>
              <Icon name="arrow" size={16} />
            </button>
            <button className="next-step-row" onClick={() => onNavigate("advisor")} type="button">
              <span className="next-step-icon"><Icon name="messages" size={18} /></span>
              <span className="next-step-copy"><strong>Run a guided profile check</strong><small>Save results and revisit them in your session history.</small></span>
              <Icon name="arrow" size={16} />
            </button>
          </div>
        </div>

        <aside className="panel coverage-panel">
          <div className="coverage-top"><span className="coverage-icon"><Icon name="shield" size={20} /></span><span className="coverage-status">SOURCE-AWARE</span></div>
          <h3>Evidence over guesswork.</h3>
          <p>EduPath only evaluates rules currently marked source-verified and within their validity window. Missing criteria are treated as unknown, not guessed.</p>
          <div className="coverage-divider" />
          <div className="coverage-stat"><span>Currently evaluable programmes</span><strong>{availableRules.length}</strong></div>
          <button className="text-link-button" onClick={() => onNavigate("eligibility")} type="button">See available rules <Icon name="arrow" size={14} /></button>
        </aside>
      </section>

      <section className="panel recent-programs-panel">
        <div className="panel-heading panel-heading-spaced">
          <div><span className="section-kicker">PROGRAMME EXPLORER</span><h3>Start with what is verified</h3></div>
          <button className="text-link-button" onClick={() => onNavigate("eligibility")} type="button">View all rules <Icon name="arrow" size={14} /></button>
        </div>
        {availableRules.length ? (
          <div className="programme-preview-grid">
            {availableRules.slice(0, 4).map((rule) => (
              <div className="programme-preview" key={rule.university_id + rule.program_id + rule.cycle}>
                <div className="preview-top"><span className="preview-initial">{String(rule.university_id || "?").slice(0, 1).toUpperCase()}</span><span className="cycle-label">{rule.cycle}</span></div>
                <h4>{rule.program_name || humanize(rule.program_id)}</h4>
                <p>{humanize(rule.university_id)}</p>
                <span className="verified-label"><Icon name="check" size={13} /> Source-verified rule</span>
              </div>
            ))}
          </div>
        ) : <p className="empty-inline">Programme rules are not available from the API yet. Check that the backend is running and refresh.</p>}
        <p className="notice-text">This catalogue is intentionally incomplete. A university not shown here is not automatically unsuitable; its criteria may need research.</p>
      </section>
    </div>
  );
}

function EligibilityPage({ profile, rules, selectedRuleId, setSelectedRuleId, evaluation, setEvaluation, busy, onEvaluate, onNavigate }) {
  const availableRules = useMemo(() => rules.filter((rule) => rule.evaluation_available), [rules]);
  const [query, setQuery] = useState("");
  const [universityFilter, setUniversityFilter] = useState("all");

  const visibleRules = availableRules.filter((rule) => {
    const label = (rule.program_name || rule.program_id || "") + " " + (rule.university_id || "") + " " + (rule.cycle || "");
    const matchesText = label.toLowerCase().includes(query.toLowerCase().trim());
    const matchesUniversity = universityFilter === "all" || rule.university_id === universityFilter;
    return matchesText && matchesUniversity;
  });
  const selectedRule = availableRules.find((rule) => (rule.university_id + "|" + rule.program_id + "|" + rule.cycle) === selectedRuleId) || availableRules[0] || null;
  const availableUniversities = Array.from(new Set(availableRules.map((rule) => rule.university_id))).sort();

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div><span className="eyebrow">SOURCE-BACKED COMPARISON</span><h2>Program finder</h2><p>Explore the rules EduPath can currently evaluate, then check them against your saved marks and subjects.</p></div>
        <span className="private-tag"><Icon name="shield" size={14} /> Rules, not predictions</span>
      </section>

      {!profile ? (
        <section className="profile-needed-banner">
          <div className="needed-icon"><Icon name="user" size={21} /></div>
          <div><h3>Save your academic profile first</h3><p>The checker needs your qualification, marks, and subjects to evaluate eligibility accurately.</p></div>
          <button className="button button-primary" onClick={() => onNavigate("profile")} type="button">Add profile <Icon name="arrow" size={15} /></button>
        </section>
      ) : null}

      <section className="checker-layout">
        <div className="panel checker-panel">
          <div className="panel-heading">
            <div><span className="section-kicker">ELIGIBILITY CHECK</span><h3>Check a programme</h3></div>
            <span className="verified-count"><Icon name="check" size={13} /> {availableRules.length} verified</span>
          </div>
          <p className="panel-description">Choose one of the programmes whose current criteria are ready for deterministic evaluation.</p>
          <label className="field-label" htmlFor="selected-program">Programme</label>
          <select
            id="selected-program"
            value={selectedRule ? selectedRule.university_id + "|" + selectedRule.program_id + "|" + selectedRule.cycle : ""}
            onChange={(event) => {
              setSelectedRuleId(event.target.value);
              setEvaluation(null);
            }}
            disabled={!availableRules.length}
          >
            {availableRules.map((rule) => (
              <option key={rule.university_id + "|" + rule.program_id + "|" + rule.cycle} value={rule.university_id + "|" + rule.program_id + "|" + rule.cycle}>
                {rule.program_name || humanize(rule.program_id)} — {humanize(rule.university_id)} ({rule.cycle})
              </option>
            ))}
          </select>
          {selectedRule ? (
            <div className="selected-rule-note">
              <div><span className="small-label">UNIVERSITY</span><strong>{humanize(selectedRule.university_id)}</strong></div>
              <div><span className="small-label">ADMISSION CYCLE</span><strong>{selectedRule.cycle}</strong></div>
              <div><span className="small-label">RULE VERSION</span><strong>{selectedRule.version}</strong></div>
            </div>
          ) : <p className="empty-inline">No rules are ready for evaluation right now.</p>}
          <button className="button button-primary full-button" type="button" onClick={onEvaluate} disabled={busy || !profile || !selectedRule}>
            {busy ? "Checking criteria…" : "Evaluate my profile"} {!busy ? <Icon name="arrow" size={16} /> : null}
          </button>
          <p className="field-help">Your saved profile is used for this request and is not copied into browser storage.</p>
        </div>

        <div className="panel evaluation-panel">
          {!evaluation ? (
            <div className="evaluation-placeholder">
              <div className="placeholder-orbit"><span><Icon name="book" size={24} /></span></div>
              <h3>Your result will appear here</h3>
              <p>We will show the listed requirements that your profile meets, misses, or needs to clarify.</p>
              <div className="placeholder-steps"><span><i>1</i> Choose a programme</span><span><i>2</i> Evaluate your profile</span><span><i>3</i> Review checks and sources</span></div>
            </div>
          ) : (
            <div className="evaluation-result">
              <div className="evaluation-result-heading"><span className="section-kicker">YOUR RESULT</span><StatusPill status={evaluation.status} /></div>
              <h3>{statusLabel(evaluation.status)}</h3>
              <p className="evaluation-explanation">{evaluation.disclaimer || "This result checks minimum eligibility criteria and is not an admission decision."}</p>
              {evaluation.rule_availability?.available === false ? (
                <div className="inline-warning"><strong>Rule unavailable</strong><span>{evaluation.rule_availability.reason}</span></div>
              ) : null}
              <RequirementList checks={evaluation.checks || []} />
              <div className="evaluation-sources">
                <span className="small-label">SOURCE LINKS</span>
                <SourceLinks sources={evaluation.source_details || (evaluation.source_urls || []).map((url) => ({ url, title: "Admissions source" }))} />
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="panel explorer-panel">
        <div className="panel-heading panel-heading-spaced">
          <div><span className="section-kicker">AVAILABLE CATALOGUE</span><h3>Explore current rules</h3><p className="panel-subtitle">Only programmes with currently evaluable source records appear here.</p></div>
          <span className="result-count">{visibleRules.length} shown</span>
        </div>
        <div className="explorer-filters">
          <label className="search-field" htmlFor="rule-search"><Icon name="search" size={16} /><input id="rule-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search programme or university" /></label>
          <label className="filter-select" htmlFor="university-filter"><span className="sr-only">Filter by university</span><select id="university-filter" value={universityFilter} onChange={(event) => setUniversityFilter(event.target.value)}><option value="all">All universities</option>{availableUniversities.map((id) => <option key={id} value={id}>{humanize(id)}</option>)}</select></label>
        </div>
        {visibleRules.length ? (
          <div className="explorer-grid">
            {visibleRules.map((rule) => (
              <article className="explorer-card" key={rule.university_id + "|" + rule.program_id + "|" + rule.cycle}>
                <div className="explorer-card-top"><span className="preview-initial">{String(rule.university_id || "?").slice(0, 1).toUpperCase()}</span><span className="verified-label"><Icon name="check" size={12} /> Verified</span></div>
                <h4>{rule.program_name || humanize(rule.program_id)}</h4>
                <p>{humanize(rule.university_id)} <span className="muted-dot">·</span> {rule.cycle}</p>
                <p className="explorer-rule-note">{rule.note || "Check the linked official criteria for the active campus and intake."}</p>
                <SourceLinks sources={(rule.source_details || []).filter((source) => source.verification_status === "verified")} />
                <button className="button button-secondary full-button" type="button" onClick={() => {
                  setSelectedRuleId(rule.university_id + "|" + rule.program_id + "|" + rule.cycle);
                  setEvaluation(null);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}>Check this programme <Icon name="arrow" size={14} /></button>
              </article>
            ))}
          </div>
        ) : <p className="empty-inline">No programmes match this filter.</p>}
        <p className="notice-text">The current catalogue is partial, and an eligible result does not guarantee a competitive merit position or admission.</p>
      </section>
    </div>
  );
}

function ProgramMessageView({ payload }) {
  return <ProgramCheckMessage payload={payload} />;
}

function AdvisorPage({ profile, conversations, activeConversation, onNewSession, onOpenSession, onDeleteSession, onProgramCheck, busy, onNavigate }) {
  const messages = activeConversation?.messages || [];
  return (
    <div className="page-stack">
      <section className="page-intro">
        <div><span className="eyebrow">GUIDED, SOURCE-AWARE REVIEW</span><h2>Admissions advisor</h2><p>Run a profile-based check using the currently verified rules, then revisit the cited results in your saved sessions.</p></div>
        <button className="button button-primary" type="button" onClick={onNewSession} disabled={busy}><Icon name="plus" size={16} /> New session</button>
      </section>

      <div className="advisor-layout">
        <aside className="panel session-list-panel">
          <div className="panel-heading">
            <div><span className="section-kicker">YOUR HISTORY</span><h3>Saved sessions</h3></div>
            <span className="session-count">{conversations.length}</span>
          </div>
          {conversations.length ? (
            <div className="session-list">
              {conversations.map((conversation) => (
                <div className={"session-row-wrap " + (activeConversation?.id === conversation.id ? "session-active" : "")} key={conversation.id}>
                  <button className="session-row" type="button" onClick={() => onOpenSession(conversation.id)}>
                    <span className="session-icon"><Icon name="messages" size={16} /></span>
                    <span className="session-copy"><strong>{conversation.title}</strong><small>{formatDate(conversation.updated_at)}</small></span>
                  </button>
                  <button className="icon-button session-delete" type="button" onClick={() => onDeleteSession(conversation.id)} aria-label={"Delete session " + conversation.title} title="Delete session"><Icon name="trash" size={14} /></button>
                </div>
              ))}
            </div>
          ) : (
            <div className="session-empty"><span className="session-empty-icon"><Icon name="messages" size={19} /></span><strong>No saved sessions yet</strong><p>Start a guided profile check to create your first review.</p></div>
          )}
          <p className="sidebar-note">Your sessions are private to your account. Deleting a session permanently removes its messages.</p>
        </aside>

        <section className="panel advisor-thread-panel">
          <div className="advisor-thread-header">
            <div className="advisor-avatar"><Icon name="book" size={18} /></div>
            <div><h3>{activeConversation?.title || "Guided admissions review"}</h3><p><span className="online-dot" /> Deterministic • Source-aware</p></div>
            {activeConversation ? <span className="thread-private"><Icon name="lock" size={13} /> Private</span> : null}
          </div>

          {messages.length ? (
            <div className="message-list">
              {messages.map((message) => {
                const programCheck = parseProgramCheck(message);
                return (
                  <div className={"message-row message-" + message.role} key={message.id}>
                    <div className={"message-avatar message-avatar-" + message.role}>{message.role === "assistant" ? <Icon name="book" size={15} /> : <Icon name="user" size={15} />}</div>
                    <div className="message-body">
                      <div className="message-meta"><strong>{message.role === "assistant" ? "EduPath guide" : "You"}</strong><span>{formatDate(message.created_at)}</span></div>
                      {programCheck ? <ProgramMessageView payload={programCheck} /> : <p className="plain-message-content">{message.content}</p>}
                      {message.role === "assistant" && !programCheck && message.citations?.length ? <SourceLinks sources={message.citations} /> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="advisor-welcome">
              <div className="welcome-illustration"><div className="welcome-paper"><span /><span /><span /><b>✓</b></div><span className="welcome-spark welcome-spark-one" /><span className="welcome-spark welcome-spark-two" /></div>
              <span className="eyebrow">START WITH YOUR PROFILE</span>
              <h3>Get a clearer picture of your options.</h3>
              <p>EduPath can compare your saved academic details with the currently verified computing-program rules. It will show checks and source links rather than guess at your admission chances.</p>
              {!profile ? (
                <button className="button button-primary" type="button" onClick={() => onNavigate("profile")}>Save my profile first <Icon name="arrow" size={15} /></button>
              ) : (
                <div className="guided-actions">
                  <button className="guided-action-card" type="button" onClick={() => onProgramCheck("find_matches")} disabled={busy}>
                    <span className="guided-action-icon"><Icon name="search" size={18} /></span><span><strong>Find my program matches</strong><small>Compare your profile with verified rules.</small></span><Icon name="arrow" size={15} />
                  </button>
                  <button className="guided-action-card" type="button" onClick={() => onProgramCheck("show_gaps")} disabled={busy}>
                    <span className="guided-action-icon guided-action-icon-amber"><Icon name="book" size={18} /></span><span><strong>Show gaps and checks</strong><small>Review minimums and missing information.</small></span><Icon name="arrow" size={15} />
                  </button>
                </div>
              )}
            </div>
          )}

          {messages.length && profile ? (
            <div className="advisor-composer">
              <div className="composer-caption"><Icon name="shield" size={14} /><span>Run a new check on your saved academic profile</span></div>
              <div className="composer-actions">
                <button className="button button-primary" type="button" onClick={() => onProgramCheck("find_matches")} disabled={busy}>{busy ? "Checking…" : "Find program matches"} <Icon name="arrow" size={15} /></button>
                <button className="button button-secondary" type="button" onClick={() => onProgramCheck("show_gaps")} disabled={busy}>Show gaps and checks</button>
              </div>
            </div>
          ) : null}
        </section>
      </div>
      <div className="advisor-limit-note"><Icon name="shield" size={16} /><p><strong>Demo-safe by design:</strong> this guided workflow uses deterministic eligibility rules, not an unrestricted chatbot. Its results are limited to available source-verified programmes and do not predict admission.</p></div>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="loading-mark">EP</div>
      <div className="loading-spinner" />
      <strong>Preparing your workspace</strong>
      <p>Connecting to your admissions data.</p>
    </div>
  );
}

export default function App() {
  const [booting, setBooting] = useState(true);
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [user, setUser] = useState(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [page, setPage] = useState("overview");
  const [authBusy, setAuthBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [profile, setProfile] = useState(null);
  const [draft, setDraft] = useState({ ...EMPTY_DRAFT });
  const [catalog, setCatalog] = useState(null);
  const [rules, setRules] = useState([]);
  const [universities, setUniversities] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [selectedRuleId, setSelectedRuleId] = useState("");
  const [evaluation, setEvaluation] = useState(null);

  const showError = (value) => {
    setToast("");
    setError(value || "The request could not be completed.");
  };

  const loadWorkspace = async () => {
    const [catalogData, rulesData, universityData, profileData, sessionsData] = await Promise.all([
      apiRequest("/admissions/catalog"),
      apiRequest("/admissions/rules"),
      apiRequest("/admissions/universities"),
      apiRequest("/profile/me").catch((problem) => {
        if (problem instanceof ApiError && problem.status === 404) return null;
        throw problem;
      }),
      apiRequest("/conversations?limit=30"),
    ]);
    setCatalog(catalogData);
    setRules(rulesData.rules || []);
    setUniversities(universityData.universities || []);
    setProfile(profileData);
    setDraft(makeDraft(profileData));
    setConversations(sessionsData || []);
    setSelectedRuleId((current) => {
      if (current && (rulesData.rules || []).some((rule) => rule.evaluation_available && (rule.university_id + "|" + rule.program_id + "|" + rule.cycle) === current)) return current;
      const first = (rulesData.rules || []).find((rule) => rule.evaluation_available);
      return first ? first.university_id + "|" + first.program_id + "|" + first.cycle : "";
    });
  };

  useEffect(() => {
    let alive = true;
    const bootstrap = async () => {
      try {
        const csrfResponse = await bootstrapCsrf();
        if (!alive) return;
        setCsrfToken(csrfResponse.csrf_token || "");
        const currentUser = await apiRequest("/auth/me").catch((problem) => {
          if (problem instanceof ApiError && problem.status === 401) return null;
          throw problem;
        });
        if (!alive) return;
        setUser(currentUser);
        if (currentUser) {
          await loadWorkspace();
          if (!alive) return;
        }
        setApiUnavailable(false);
      } catch (problem) {
        if (!alive) return;
        setApiUnavailable(true);
        showError(problem instanceof Error ? problem.message : "EduPath could not reach the API.");
      } finally {
        if (alive) setBooting(false);
      }
    };
    bootstrap();
    return () => { alive = false; };
  }, []);

  const handleAuth = async ({ mode, email, password }) => {
    setAuthBusy(true);
    setError("");
    setToast("");
    try {
      const csrf = await bootstrapCsrf();
      setCsrfToken(csrf.csrf_token || "");
      const response = await apiRequest("/auth/" + mode, {
        method: "POST",
        csrfToken: csrf.csrf_token,
        body: { email, password },
      });
      setCsrfToken(response.csrf_token || "");
      setUser(response.user);
      await loadWorkspace();
      setPage("overview");
      setActiveConversation(null);
      setToast(mode === "register" ? "Your account is ready. Add your academic profile to get started." : "Welcome back. Your workspace is ready.");
      setApiUnavailable(false);
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "Authentication failed.");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    try {
      if (csrfToken) await apiRequest("/auth/logout", { method: "POST", csrfToken });
    } catch {
      // Always clear local UI state. The server-side session expires or is revoked independently.
    } finally {
      setUser(null);
      setCsrfToken("");
      setProfile(null);
      setDraft({ ...EMPTY_DRAFT });
      setRules([]);
      setCatalog(null);
      setUniversities([]);
      setConversations([]);
      setActiveConversation(null);
      setEvaluation(null);
      setPage("overview");
      setBusy(false);
      setToast("");
      setError("");
    }
  };

  const saveProfile = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setToast("");
    try {
      const qualification = draft.qualification.trim();
      const ssc = Number(draft.ssc_percent);
      const hssc = Number(draft.hssc_percent);
      const subjects = draft.subjects.split(",").map((value) => value.trim()).filter(Boolean);
      if (!qualification || !Number.isFinite(ssc) || !Number.isFinite(hssc) || ssc < 0 || ssc > 100 || hssc < 0 || hssc > 100 || !subjects.length) {
        throw new Error("Enter a qualification, valid SSC/HSSC percentages, and at least one subject.");
      }
      if (subjects.some((subject) => subject.length > 80)) {
        throw new Error("Each subject name must be 80 characters or fewer.");
      }
      const subjectPercentages = parseSubjectMarks(draft.subject_percentages);
      const response = await apiRequest("/profile/me", {
        method: "PUT",
        csrfToken,
        body: {
          qualification,
          ssc_percent: ssc,
          hssc_percent: hssc,
          subjects,
          subject_percentages: subjectPercentages,
          equivalency_status: draft.equivalency_status || "unknown",
        },
      });
      setProfile(response);
      setDraft(makeDraft(response));
      setEvaluation(null);
      setToast("Your academic profile was saved securely.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "Your profile could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const deleteProfile = async () => {
    if (!window.confirm("Delete your saved academic profile? This cannot be undone.")) return;
    setBusy(true);
    setError("");
    setToast("");
    try {
      await apiRequest("/profile/me", { method: "DELETE", csrfToken });
      setProfile(null);
      setDraft({ ...EMPTY_DRAFT });
      setEvaluation(null);
      setToast("Your saved academic profile was deleted.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "The profile could not be deleted.");
    } finally {
      setBusy(false);
    }
  };

  const evaluateSelectedRule = async () => {
    const rule = rules.find((item) => item.evaluation_available && (item.university_id + "|" + item.program_id + "|" + item.cycle) === selectedRuleId);
    if (!rule) {
      showError("Choose a programme with a currently verified rule.");
      return;
    }
    if (!profile) {
      setPage("profile");
      showError("Save your academic profile before running an eligibility check.");
      return;
    }
    setBusy(true);
    setError("");
    setToast("");
    setEvaluation(null);
    try {
      const response = await apiRequest("/admissions/evaluate", {
        method: "POST",
        body: {
          university_id: rule.university_id,
          program_id: rule.program_id,
          cycle: String(rule.cycle),
          profile: {
            qualification: profile.qualification,
            ssc_percent: profile.ssc_percent,
            hssc_percent: profile.hssc_percent,
            subjects: profile.subjects || [],
            subject_percentages: profile.subject_percentages || {},
            equivalency_status: profile.equivalency_status || "unknown",
            cycle: String(rule.cycle),
          },
        },
      });
      setEvaluation(response);
      setToast("Eligibility checks completed.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "The eligibility check could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const refreshConversations = async () => {
    const response = await apiRequest("/conversations?limit=30");
    setConversations(response || []);
  };

  const createSession = async () => {
    setBusy(true);
    setError("");
    setToast("");
    try {
      const created = await apiRequest("/conversations", {
        method: "POST",
        csrfToken,
        body: { title: "Admissions profile review" },
      });
      const detail = await apiRequest("/conversations/" + created.id);
      setActiveConversation(detail);
      await refreshConversations();
      setPage("advisor");
      setToast("New private review session created.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "A session could not be created.");
    } finally {
      setBusy(false);
    }
  };

  const openSession = async (id) => {
    setBusy(true);
    setError("");
    try {
      const detail = await apiRequest("/conversations/" + id);
      setActiveConversation(detail);
      setPage("advisor");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "This session could not be opened.");
    } finally {
      setBusy(false);
    }
  };

  const deleteSession = async (id) => {
    if (!window.confirm("Permanently delete this session and its messages?")) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest("/conversations/" + id, { method: "DELETE", csrfToken });
      setConversations((current) => current.filter((item) => item.id !== id));
      if (activeConversation?.id === id) setActiveConversation(null);
      setToast("Session and its saved messages deleted.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "The session could not be deleted.");
    } finally {
      setBusy(false);
    }
  };

  const runProgramCheck = async (mode) => {
    if (!profile) {
      setPage("profile");
      showError("Save your academic profile before running a guided programme check.");
      return;
    }
    setBusy(true);
    setError("");
    setToast("");
    try {
      let conversationId = activeConversation?.id;
      if (!conversationId) {
        const created = await apiRequest("/conversations", {
          method: "POST",
          csrfToken,
          body: { title: "Admissions profile review" },
        });
        conversationId = created.id;
      }
      await apiRequest("/conversations/" + conversationId + "/program-check", {
        method: "POST",
        csrfToken,
        body: { mode },
      });
      const detail = await apiRequest("/conversations/" + conversationId);
      setActiveConversation(detail);
      await refreshConversations();
      setToast("Your cited programme review was saved to this session.");
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : "The guided programme check could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  if (booting) return <LoadingScreen />;

  if (!user) {
    return (
      <AuthScreen
        onSubmit={handleAuth}
        busy={authBusy}
        error={error}
        onClearError={() => setError("")}
        apiUnavailable={apiUnavailable}
      />
    );
  }

  const pageTitle = {
    overview: ["Your workspace", "Overview"],
    profile: ["Account details", "My profile"],
    eligibility: ["Explore programme criteria", "Program finder"],
    advisor: ["Your saved reviews", "Guided advisor"],
  }[page] || ["Your workspace", "Overview"];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup sidebar-brand">
          <span className="brand-mark">EP</span>
          <span className="brand-word">EduPath<span className="brand-period">.</span></span>
        </div>
        <div className="sidebar-overline">ADMISSIONS WORKSPACE</div>
        <nav className="primary-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={"nav-item " + (page === item.id ? "nav-item-active" : "")}
              onClick={() => { setPage(item.id); setError(""); setToast(""); }}
              aria-current={page === item.id ? "page" : undefined}
            >
              <span className="nav-icon"><Icon name={item.icon} size={17} /></span>
              <span>{item.label}</span>
              {item.id === "advisor" && conversations.length ? <span className="nav-count">{conversations.length}</span> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-safety-card">
            <span className="safety-card-icon"><Icon name="shield" size={17} /></span>
            <strong>Source-aware by default</strong>
            <p>Unknown rules stay unknown. No made-up eligibility results.</p>
          </div>
          <div className="account-row">
            <span className="account-avatar">{String(user.email || "S").slice(0, 1).toUpperCase()}</span>
            <span className="account-copy"><strong>Signed in</strong><small title={user.email}>{user.email}</small></span>
            <button className="icon-button logout-button" type="button" onClick={handleLogout} aria-label="Sign out" title="Sign out" disabled={busy}><Icon name="logout" size={17} /></button>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-heading"><span className="topbar-crumb">{pageTitle[0]}</span><h1>{pageTitle[1]}</h1></div>
          <div className="topbar-actions">
            <span className="api-status"><span className="api-status-dot" /> API connected</span>
            <button className="topbar-account" type="button" onClick={() => setPage("profile")}><span className="small-avatar">{String(user.email || "S").slice(0, 1).toUpperCase()}</span><span>My account</span></button>
          </div>
        </header>

        <main className="page-content">
          {error ? <div className="alert alert-error global-alert" role="alert"><span>{error}</span><button type="button" className="alert-dismiss" onClick={() => setError("")} aria-label="Dismiss message">×</button></div> : null}
          {toast ? <div className="alert alert-success global-alert" role="status"><Icon name="check" size={16} /><span>{toast}</span><button type="button" className="alert-dismiss" onClick={() => setToast("")} aria-label="Dismiss message">×</button></div> : null}

          {page === "overview" ? (
            <OverviewPage
              user={user}
              profile={profile}
              catalog={catalog}
              rules={rules}
              universities={universities}
              conversations={conversations}
              onNavigate={setPage}
            />
          ) : null}
          {page === "profile" ? (
            <ProfilePage
              profile={profile}
              draft={draft}
              setDraft={setDraft}
              onSave={saveProfile}
              onDelete={deleteProfile}
              busy={busy}
              onNavigate={setPage}
            />
          ) : null}
          {page === "eligibility" ? (
            <EligibilityPage
              profile={profile}
              rules={rules}
              selectedRuleId={selectedRuleId}
              setSelectedRuleId={setSelectedRuleId}
              evaluation={evaluation}
              setEvaluation={setEvaluation}
              busy={busy}
              onEvaluate={evaluateSelectedRule}
              onNavigate={setPage}
            />
          ) : null}
          {page === "advisor" ? (
            <AdvisorPage
              profile={profile}
              conversations={conversations}
              activeConversation={activeConversation}
              onNewSession={createSession}
              onOpenSession={openSession}
              onDeleteSession={deleteSession}
              onProgramCheck={runProgramCheck}
              busy={busy}
              onNavigate={setPage}
            />
          ) : null}

          <footer className="workspace-footer">
            <span>EduPath <span className="footer-dot">·</span> Admissions guidance for Pakistan</span>
            <span><Icon name="shield" size={13} /> Your saved profile is account-scoped</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
