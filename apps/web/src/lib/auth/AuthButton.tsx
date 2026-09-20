"use client";

import { Spinner } from "@/components/ui/spinner";

import { Button } from "@/components/ui/button";

type AuthButtonProps = React.ComponentProps<typeof Button> & {
    loading?: boolean;
};

function AuthButton({
    loading = false,
    children,
    disabled,
    ...props
}: AuthButtonProps) {
    return (
        <Button disabled={disabled || loading} {...props}>
            {loading ? (
                <Spinner
                    aria-hidden="true"
                    className="size-4"
                />
            ) : null}
            {children}
        </Button>
    );
}

export { AuthButton };
