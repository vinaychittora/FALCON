import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import Icon from "../components/Icon";
import { usePoll } from "../hooks/usePoll";
import "./help.css";

type GuideEntry = {
  slug: string;
  title: string;
  summary: string;
  section: string;
};
type HandbookEntry = {
  slug: string;
  title: string;
  summary: string;
  html: string | null;
  pdf: string | null;
};
type HelpIndex = { guides: GuideEntry[]; handbooks: HandbookEntry[] };
type GuidePage = GuideEntry & {
  source: string;
  html: string;
  headings: { id: string; text: string; level: number }[];
};
type SearchResult = {
  slug: string;
  guide: string;
  section: string | null;
  heading: string;
  snippet: string;
};

/** "user-guide/live" -> { slug: "user-guide", section: "live" } */
export function parseHelpRoute(route: string): {
  slug: string;
  section: string | null;
} {
  const [slug, section] = route.split("/");
  return { slug: slug || "start", section: section || null };
}

export function helpHref(slug: string, section?: string | null) {
  return `#/help/${slug}${section ? `/${section}` : ""}`;
}

/** Small link to the matching help section, shown in page headers. */
export function HelpLink({
  slug,
  section,
  label = "Help",
}: {
  slug: string;
  section?: string;
  label?: string;
}) {
  return (
    <a
      className="help-link"
      href={helpHref(slug, section)}
      title="Open the guide for this page"
    >
      <Icon name="question" size={15} /> {label}
    </a>
  );
}

const HANDBOOK_SLUGS = ["node-build", "user-handbook"];

export default function HelpPage({ route }: { route: string }) {
  const { slug, section } = parseHelpRoute(route);
  const index = usePoll(() => api<HelpIndex>("/help"), 0);
  const isHandbook = HANDBOOK_SLUGS.includes(slug);
  const handbook = index.data?.handbooks.find((item) => item.slug === slug);
  const page = usePoll(
    () =>
      isHandbook
        ? Promise.resolve(null)
        : api<GuidePage>(`/help/guides/${encodeURIComponent(slug)}`),
    0,
    slug,
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const article = useRef<HTMLElement>(null);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      const timer = setTimeout(() => setResults(null), 0);
      return () => clearTimeout(timer);
    }
    let alive = true;
    const timer = setTimeout(() => {
      api<{ results: SearchResult[] }>(
        `/help/search?q=${encodeURIComponent(text)}`,
      )
        .then((value) => {
          if (alive) setResults(value.results);
        })
        .catch(() => {
          if (alive) setResults([]);
        });
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query]);

  // A new page starts at the top; a linked section is scrolled to once it is shown.
  useEffect(() => {
    if (!section) window.scrollTo({ top: 0 });
  }, [slug, section, results]);
  useEffect(() => {
    if (!page.data || page.data.slug !== slug) return;
    const target = section ? document.getElementById(section) : null;
    if (target) target.scrollIntoView({ block: "start" });
  }, [page.data, slug, section]);

  const sections = useMemo(() => {
    const groups: Record<string, GuideEntry[]> = {};
    for (const guide of index.data?.guides ?? [])
      (groups[guide.section] ??= []).push(guide);
    return Object.entries(groups);
  }, [index.data]);
  const current = page.data && page.data.slug === slug ? page.data : null;
  const toc = current?.headings.filter((heading) => heading.level <= 3) ?? [];

  return (
    <div
      className={`page help-page${!results && toc.length > 1 ? "" : " no-toc"}`}
    >
      <aside className="help-nav" aria-label="Help contents">
        <div className="help-search">
          <Icon name="filter" size={15} />
          <input
            type="search"
            placeholder="Search all guides"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search all guides"
          />
        </div>
        {sections.map(([name, guides]) => (
          <nav key={name} aria-label={name}>
            <h2>{name}</h2>
            {guides.map((guide) => (
              <a
                key={guide.slug}
                href={helpHref(guide.slug)}
                className={guide.slug === slug ? "active" : ""}
                aria-current={guide.slug === slug ? "page" : undefined}
              >
                {guide.title}
              </a>
            ))}
          </nav>
        ))}
        {!!index.data?.handbooks.length && (
          <nav aria-label="Handbooks">
            <h2>Handbooks</h2>
            {index.data.handbooks.map((book) => (
              <a
                key={book.slug}
                href={helpHref(book.slug)}
                className={book.slug === slug ? "active" : ""}
              >
                {book.title}
              </a>
            ))}
          </nav>
        )}
      </aside>

      <main className="help-main" ref={article}>
        {results ? (
          <section className="help-article">
            <span className="eyebrow">Search</span>
            <h1>Results for “{query.trim()}”</h1>
            {!results.length && (
              <p>Nothing found. Try fewer or different words.</p>
            )}
            <ol className="help-results">
              {results.map((result, number) => (
                <li key={`${result.slug}-${result.section}-${number}`}>
                  <a
                    href={helpHref(result.slug, result.section)}
                    onClick={() => {
                      setQuery("");
                      setResults(null);
                    }}
                  >
                    <strong>{result.heading}</strong>
                    <small>{result.guide}</small>
                  </a>
                  <p>{result.snippet}</p>
                </li>
              ))}
            </ol>
          </section>
        ) : handbook ? (
          <section className="help-article help-handbook">
            <span className="eyebrow">Handbook</span>
            <h1>{handbook.title}</h1>
            <p className="lede">{handbook.summary}</p>
            <div className="help-actions">
              {handbook.pdf && (
                <a className="button primary" href={handbook.pdf} download>
                  <Icon name="download" size={16} /> Download PDF
                </a>
              )}
              {handbook.html && handbook.slug === "node-build" && (
                <a
                  className="button"
                  href={handbook.html}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Icon name="external" size={16} /> Open in its own tab
                </a>
              )}
            </div>
            {handbook.slug === "node-build" && handbook.html ? (
              <iframe
                className="help-frame"
                src={handbook.html}
                title={handbook.title}
              />
            ) : (
              <p>
                The printable handbook contains the same text as these guides:{" "}
                {index.data?.guides
                  .filter((guide) =>
                    [
                      "user-guide",
                      "install",
                      "sensor-node",
                      "data-export",
                      "operations",
                    ].includes(guide.slug),
                  )
                  .map((guide, position, list) => (
                    <span key={guide.slug}>
                      <a href={helpHref(guide.slug)}>{guide.title}</a>
                      {position < list.length - 1 ? ", " : "."}
                    </span>
                  ))}
              </p>
            )}
          </section>
        ) : current ? (
          <article className="help-article">
            <span className="eyebrow">{current.section}</span>
            <h1>{current.title}</h1>
            <p className="lede">{current.summary}</p>
            {/* Server-rendered from the repository's Markdown; all text is escaped before markup is added. */}
            <div
              className="help-content"
              dangerouslySetInnerHTML={{ __html: current.html }}
            />
            <p className="help-source">
              Source: <code>{current.source}</code> · edit it to update this
              page
            </p>
          </article>
        ) : (
          <p className="muted">{page.error || index.error || "Loading…"}</p>
        )}
      </main>

      {!results && toc.length > 1 && (
        <nav className="help-toc" aria-label="On this page">
          <h2>On this page</h2>
          {toc.map((heading) => (
            <a
              key={heading.id}
              href={helpHref(slug, heading.id)}
              className={`level-${heading.level}${heading.id === section ? " active" : ""}`}
            >
              {heading.text}
            </a>
          ))}
        </nav>
      )}
    </div>
  );
}
