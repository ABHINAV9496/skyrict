export interface PasswordRequirement {
  label: string;
  test: (password: string) => boolean;
}

export const passwordRequirements: PasswordRequirement[] = [
  { label: "At least 12 characters", test: (p) => p.length >= 12 },
  { label: "An uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "A number", test: (p) => /\d/.test(p) },
  { label: "A special character", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

export type PasswordStrengthScore = 0 | 1 | 2 | 3 | 4;

export function passwordStrength(password: string): PasswordStrengthScore {
  let score = 0;
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  return score as PasswordStrengthScore;
}

export function allRequirementsMet(password: string): boolean {
  return passwordRequirements.every((requirement) =>
    requirement.test(password),
  );
}

export const strengthLabels = ["Weak", "Fair", "Good", "Strong"] as const;

export const strengthColors = [
  "bg-primary/25",
  "bg-primary/50",
  "bg-primary/80",
  "bg-primary",
] as const;
