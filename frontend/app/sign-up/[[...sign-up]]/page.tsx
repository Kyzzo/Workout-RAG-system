import { SignUp } from "@clerk/nextjs";

export default function Page() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-10">
      <SignUp />
    </div>
  );
}
