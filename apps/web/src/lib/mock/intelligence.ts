/**
 * Mock market-intelligence search results for the search-engine world.
 *
 * A single `search(query)` returns grouped sections (competitors, winning
 * products, niches, trends) so the frontend can render a Perplexity-style
 * results page without a real intelligence service. Wire these to the real
 * pipeline later by swapping the API route's data source.
 */

export interface SearchResult {
  title: string;
  source: string;
  url: string;
  snippet: string;
  confidence: number;
  timeframe: string;
}

export interface SearchSection {
  id: "competitors" | "winning-products" | "niches" | "trends";
  label: string;
  description: string;
  results: SearchResult[];
}

export interface SearchResponse {
  query: string;
  generatedAt: string;
  summary: string;
  sections: SearchSection[];
}

function pick<T>(items: T[], hash: number): T {
  return items[Math.abs(hash) % items.length];
}

/** Deterministic hash so the same query returns stable mock results. */
function hashQuery(query: string): number {
  let hash = 0;
  for (let i = 0; i < query.length; i++) {
    hash = (hash * 31 + query.charCodeAt(i)) | 0;
  }
  return hash;
}

const SUMMARIES = [
  "Based on recent signals across Trends, Reddit, YouTube, GitHub, and news, momentum around this space is rising but fragmented - a handful of entrants are winning distribution while most niche plays remain underserved.",
  "Cross-referencing five sources points to a market where demand is consolidating around quality and speed. Competitors are moving toward bundled offers, while winning products share a focus on automation and trust.",
  "Market signals show healthy but slowing growth in the broad category, with clear whitespace in specific niches. The strongest competitors are doubling down on verticals rather than horizontal reach.",
];

export function searchIntelligence(query: string): SearchResponse {
  const hash = hashQuery(query);
  const trimmed = query.trim() || "market";
  const term = trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed;

  const base = {
    query: trimmed,
    generatedAt: new Date().toISOString(),
    summary: pick(SUMMARIES, hash),
  };

  return {
    ...base,
    sections: [
      {
        id: "competitors",
        label: "Competitors",
        description: `Who is moving in the ${term} space right now.`,
        results: [
          {
            title: `${pick(["Nimbus", "Vertex", "Orbit", "Lumen", "Forge"], hash)} expands ${term} offering`,
            source: "News · Business Wire",
            url: "#",
            snippet: `Announced a new ${term} product line targeting mid-market teams, bundling analytics and workflow tools. Early reviews point to strong retention.`,
            confidence: 0.92,
            timeframe: "Last 2 weeks",
          },
          {
            title: `Inside ${pick(["Coreline", "Halcyon", "Aptiv", "Briar", "Junction"], hash)}'s go-to-market for ${term}`,
            source: "Reddit · r/SaaS",
            url: "#",
            snippet: `Community breakdown of how a rising player is winning ${term} deals: aggressive onboarding, transparent pricing, and fast support response times.`,
            confidence: 0.78,
            timeframe: "Last month",
          },
          {
            title: `${pick(["Relay", "Common", "Pathway", "Quill", "Dove"], hash)} retreats from ${term}`,
            source: "Trends",
            url: "#",
            snippet: `Search interest for this incumbent dropped 34% quarter over quarter as users migrate to leaner ${term} tools.`,
            confidence: 0.84,
            timeframe: "Last quarter",
          },
        ],
      },
      {
        id: "winning-products",
        label: "Winning products",
        description: `Products gaining share and traction in ${term}.`,
        results: [
          {
            title: `${pick(["Fieldnote", "Stackline", "Breezeway", "Northbeam", "Cobalt"], hash)} - the ${term} product to watch`,
            source: "YouTube · 214k views",
            url: "#",
            snippet: `Reviewers consistently rank it highest for setup speed and accuracy. Adoption is accelerating among teams under 50 people.`,
            confidence: 0.9,
            timeframe: "This week",
          },
          {
            title: `Why ${pick(["Tandem", "Morrow", "Iris", "Pintail", "Acero"], hash)} is out-growing peers in ${term}`,
            source: "Reddit · r/ProductManagement",
            url: "#",
            snippet: `Thread analyzing the product-led motion behind its growth: free tier generosity, weekly shipping, and community-led docs.`,
            confidence: 0.73,
            timeframe: "Last 2 weeks",
          },
          {
            title: `${term} template packs and playbooks trend upward`,
            source: "Trends",
            url: "#",
            snippet: `Interest in ${term} templates and starter kits is up 58% - a signal that buyers want to start fast, not build from scratch.`,
            confidence: 0.81,
            timeframe: "Last month",
          },
        ],
      },
      {
        id: "niches",
        label: "Niches",
        description: `Underserved segments inside ${term}.`,
        results: [
          {
            title: `${pick(["RegTech", "HealthTech", "EdTech", "PropTech", "LogTech"], hash)} + ${term}: a crowded idea with empty shelves`,
            source: "GitHub · discussion",
            url: "#",
            snippet: `Open-source projects for ${term} in this vertical are sparse - most existing tools are horizontal. The few vertical attempts have strong early engagement.`,
            confidence: 0.88,
            timeframe: "Last quarter",
          },
          {
            title: `${term} for solo operators and micro teams`,
            source: "Reddit · r/SmallBusiness",
            url: "#",
            snippet: `Repeated demand for a lightweight ${term} option priced for 1–3 person teams. Incumbents are priced and scoped for larger orgs.`,
            confidence: 0.76,
            timeframe: "Ongoing",
          },
          {
            title: `Localized ${term} solutions gaining interest`,
            source: "YouTube · community posts",
            url: "#",
            snippet: `Creators serving non-English markets report steady questions about ${term} tools built for local compliance and language.`,
            confidence: 0.7,
            timeframe: "Last month",
          },
        ],
      },
      {
        id: "trends",
        label: "Trends",
        description: `The direction of ${term} over time.`,
        results: [
          {
            title: `${term} search interest is trending ${pick(["up 41%", "up 27%", "flat", "up 63%"], hash)}`,
            source: "Trends · Google",
            url: "#",
            snippet: `Sustained growth since Q1 with spikes correlated to product launches. Interest concentrates in North America and Europe, with emerging growth in Southeast Asia.`,
            confidence: 0.95,
            timeframe: "12 months",
          },
          {
            title: `Automation is the #1 buying driver for ${term}`,
            source: "News · Industry report",
            url: "#",
            snippet: `Across surveys, buyers of ${term} tools cite automation and time-to-value as the top two reasons to switch vendors this year.`,
            confidence: 0.85,
            timeframe: "This year",
          },
          {
            title: `${pick(["AI agents", "Embedded analytics", "API-first", "Self-serve"], hash)} reframes ${term} conversations`,
            source: "GitHub · trending topics",
            url: "#",
            snippet: `Developer discourse now frames ${term} around composability and agents rather than monolithic suites - a meaningful shift in the ecosystem.`,
            confidence: 0.79,
            timeframe: "Last 6 months",
          },
        ],
      },
    ],
  };
}
