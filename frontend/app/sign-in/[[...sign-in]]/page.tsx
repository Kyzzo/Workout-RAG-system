import { SignIn } from "@clerk/nextjs";
import Link from "next/link";

export default function Page() {
  return (
    <>
      <Link href="/" className="masthead-home auth-mark" aria-label="Citeset: back to the schedule">
        <span className="tiehole" aria-hidden />
        <span className="wordmark steel-text">Citeset</span>
      </Link>
      <SignIn />
    </>
  );
}
