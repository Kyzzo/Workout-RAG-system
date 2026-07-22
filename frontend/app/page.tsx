import { auth } from "@clerk/nextjs/server";
import ProgramForm from "./ProgramForm";
import ProgramViewer from "./ProgramViewer";

export default async function Home() {
  await auth.protect();

  return (
    <div className="flex flex-col flex-1 items-center bg-zinc-50 font-sans dark:bg-black divide-y">
      <ProgramForm />
      <ProgramViewer />
    </div>
  );
}
