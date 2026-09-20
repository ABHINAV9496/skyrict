import { Spinner } from "@/components/ui/spinner";

export default function LeaveLoading() {
    return (
        <div className="flex min-h-dvh items-center justify-center bg-background">
            <Spinner className="size-6" />
        </div>
    );
}