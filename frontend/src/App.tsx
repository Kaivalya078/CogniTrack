import { useEffect, useState } from "react";
import Health from "./pages/Health";
import Staging from "./pages/Staging";

// A hash switch instead of a router while there are two pages; a router comes with M6's pages.
const PAGES = { "#/": ["Health", Health], "#/staging": ["Staging", Staging] } as const;
type Hash = keyof typeof PAGES;

function currentHash(): Hash {
  return location.hash in PAGES ? (location.hash as Hash) : "#/";
}

export default function App() {
  const [hash, setHash] = useState(currentHash);
  useEffect(() => {
    const onChange = () => setHash(currentHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const Page = PAGES[hash][1];

  return (
    <main className="mx-auto max-w-xl p-4">
      <header className="mb-4 flex items-baseline gap-4">
        <h1 className="text-xl font-semibold">CogniTrack</h1>
        <nav className="flex gap-3 text-sm">
          {Object.entries(PAGES).map(([href, [label]]) => (
            <a key={href} href={href} className={href === hash ? "font-semibold underline" : "text-gray-600"}>
              {label}
            </a>
          ))}
        </nav>
      </header>
      <Page />
    </main>
  );
}
