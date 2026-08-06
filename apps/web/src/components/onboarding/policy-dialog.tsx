"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const termsBullets = [
  "These Terms govern your access to and use of the Skyrict workspace, dashboard, agents, and related services.",
  "You are responsible for your organization workspace, including accounts and activity within it.",
  "Paid plans are billed in advance; you can change or cancel your plan at any time from workspace settings.",
  "Use Skyrict lawfully. Do not disrupt other users or interfere with the service.",
  "We aim for high availability but cannot guarantee uninterrupted access.",
];

const privacyBullets = [
  "We collect the information you provide, such as account details and your organization profile, plus service usage data needed to run the product.",
  "We use that data to provide the service, improve Skyrict, and keep it secure. We never sell your data.",
  "Agents only act within the workspace you control and follow the permissions you set.",
  "We keep your data while your account is active and delete it when you ask.",
  "Questions? Contact us at support@skyrict.ai.",
];

function PolicyDialog() {
  return (
    <Dialog>
      <DialogTrigger className="text-sm font-medium text-primary underline-offset-4 outline-none hover:underline">
        Read the policy
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Terms of Service & Privacy Policy</DialogTitle>
          <DialogDescription>Effective date: January 1, 2026</DialogDescription>
        </DialogHeader>
        <div className="space-y-6 pr-1 text-sm leading-relaxed text-muted-foreground">
          <section className="space-y-2">
            <h3 className="font-semibold text-foreground">Terms of Service</h3>
            <ul className="list-disc space-y-1.5 pl-5">
              {termsBullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          </section>
          <section className="space-y-2">
            <h3 className="font-semibold text-foreground">Privacy Policy</h3>
            <ul className="list-disc space-y-1.5 pl-5">
              {privacyBullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { PolicyDialog };
