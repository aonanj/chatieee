"use client";
import Link from "next/link";
import Image from "next/image";

export default function NavBar() {
  return (
    <header className="sticky top-0 z-40 flex justify-center border-b border-slate-200 bg-white/90 backdrop-blur supports-backdrop-filter:bg-white/70">
      <nav className="flex h-20 w-full max-w-7xl items-center justify-between gap-6 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-5">
          <Link href="/" aria-label="ChatIEEE Home" className="inline-flex items-center gap-2">
            <Image src="/images/chatieee-logo.png" alt="ChatIEEE" width={70} height={70} className="hover:scale-110 transition-transform py-2" />
          </Link>
          <p className="text-base font-semibold uppercase tracking-[0.18em] text-[#39506B]">ChatIEEE Suite</p>
        </div>

        <div className="hidden items-center gap-6 md:flex">
          <Link href="/" className="px-6 py-3 text-lg font-semibold rounded-md hover:bg-[#d9e1eb] hover:underline text-[#3A506B]">Query</Link>
          <Link href="/ingest" className="px-6 py-3 text-lg font-semibold rounded-md hover:bg-[#d9e1eb] hover:underline text-[#3A506B]">Ingest</Link>
        </div>
      </nav>
    </header>
  );
}
