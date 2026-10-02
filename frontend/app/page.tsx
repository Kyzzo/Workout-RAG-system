import { auth } from "@clerk/nextjs/server";
import ProgramWorkspace from "./ProgramWorkspace";

export default async function Home() {
  await auth.protect();

  return (
    <div className="flex flex-col flex-1 items-center bg-zinc-50 font-sans dark:bg-black">
      <ProgramWorkspace />
    </div>
  );
}
