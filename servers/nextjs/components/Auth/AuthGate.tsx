"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Image from "next/image";
import { getApiUrl } from "@/utils/api";
import { isAuthDisabled } from "@/utils/auth";
import { formatFastApiDetail, UNAUTHORIZED_DETAIL } from "@/utils/authErrors";
import {
  PRESENTON_SPLASH_MIN_DURATION_MS,
  PresentonSplashLoader,
} from "@/components/ui/presenton-splash-loader";
import { notify } from "@/components/ui/sonner";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import { MixpanelEvent, trackEvent } from "@/utils/mixpanel";

type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
  username: string | null;
  role?: "admin" | "user" | null;
};

const initialStatus: AuthStatus = {
  configured: false,
  authenticated: false,
  username: null,
  role: null,
};

export default function AuthGate() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<AuthStatus>(initialStatus);
  const [isLoading, setIsLoading] = useState(true);
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasMetSplashDuration, setHasMetSplashDuration] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [oidcLoginEnabled, setOidcLoginEnabled] = useState(false);
  const [oidcLoginLabel, setOidcLoginLabel] = useState<string | null>(null);
  const isSetupMode = useMemo(() => !status.configured, [status.configured]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setHasMetSplashDuration(true);
    }, PRESENTON_SPLASH_MIN_DURATION_MS);

    return () => window.clearTimeout(timeout);
  }, []);

  useEffect(() => {
    if (isAuthDisabled()) {
      trackEvent(MixpanelEvent.Auth_Status_Checked, {
        configured: true,
        authenticated: true,
        auth_disabled: true,
      });
      setStatus({
        configured: true,
        authenticated: true,
        username: "electron",
        role: "admin",
      });
      setIsLoading(false);
      return;
    }

    void refreshStatus();
    void refreshOidcStatus();
  }, []);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      isLoading ||
      !status.authenticated ||
      isRedirecting
    ) {
      return;
    }

    setIsRedirecting(true);
    window.location.replace("/");
  }, [isLoading, isRedirecting, status.authenticated]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoading) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    if (params.get("reason") === "unauthorized") {
      if (status.configured && !status.authenticated) {
        trackEvent(MixpanelEvent.Auth_Unauthorized_Redirect, {
          configured: true,
        });
        notify.error(t("auth.err_unauthorized_title"), t("auth.err_unauthorized_msg"), {
          id: "auth-unauthorized-redirect",
          duration: 5000,
        });
      }
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [isLoading, status.authenticated, status.configured]);

  const refreshStatus = async () => {
    setIsLoading(true);

    try {
      const response = await fetch(getApiUrl("/api/v1/auth/status"), {
        method: "GET",
        cache: "no-store",
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error("Could not load login state");
      }

      const data = (await response.json()) as AuthStatus;
      trackEvent(MixpanelEvent.Auth_Status_Checked, {
        configured: Boolean(data.configured),
        authenticated: Boolean(data.authenticated),
        auth_disabled: false,
        role: data.role ?? null,
      });
      setStatus({
        configured: Boolean(data.configured),
        authenticated: Boolean(data.authenticated),
        username: data.username ?? null,
        role: data.role ?? null,
      });
    } catch (fetchError) {
      console.error(fetchError);
      trackEvent(MixpanelEvent.Auth_Status_Checked, {
        configured: false,
        authenticated: false,
        auth_disabled: false,
        error_message: sanitizeAnalyticsError(
          fetchError,
          "Could not load login state"
        ),
      });
      notify.error(
        t("auth.err_load_title"),
        t("auth.err_load_msg")
      );
    } finally {
      setIsLoading(false);
    }
  };

  const refreshOidcStatus = async () => {
    try {
      const response = await fetch(getApiUrl("/api/v1/auth/oidc/status"), {
        method: "GET",
        cache: "no-store",
        credentials: "include",
      });
      if (!response.ok) {
        return;
      }
      const data = (await response.json()) as {
        login_enabled?: boolean;
        login_button_label?: string;
      };
      setOidcLoginEnabled(Boolean(data.login_enabled));
      if (data.login_button_label) {
        setOidcLoginLabel(data.login_button_label);
      }
    } catch {
      // OIDC login is optional; ignore lookup failures.
    }
  };

  useEffect(() => {
    if (
      isLoading ||
      isRedirecting ||
      status.authenticated ||
      !hasMetSplashDuration
    ) {
      return;
    }

    trackEvent(MixpanelEvent.Auth_Gate_Viewed, {
      flow: status.configured ? "sign_in" : "setup",
    });
  }, [
    hasMetSplashDuration,
    isLoading,
    isRedirecting,
    status.authenticated,
    status.configured,
  ]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const cleanedUsername = username.trim();
    if (cleanedUsername.length < 3) {
      trackEvent(MixpanelEvent.Auth_Validation_Failed, {
        flow: isSetupMode ? "setup" : "sign_in",
        reason: "username_too_short",
      });
      notify.warning(
        t("auth.err_username_short_title"),
        t("auth.err_username_short_msg")
      );
      return;
    }

    const minimumPasswordLength = isSetupMode ? 8 : 6;
    if (password.length < minimumPasswordLength) {
      trackEvent(MixpanelEvent.Auth_Validation_Failed, {
        flow: isSetupMode ? "setup" : "sign_in",
        reason: "password_too_short",
      });
      notify.warning(
        t("auth.err_password_short_title"),
        t("auth.err_password_short_msg", { min: minimumPasswordLength })
      );
      return;
    }

    if (isSetupMode && password !== confirmPassword) {
      trackEvent(MixpanelEvent.Auth_Validation_Failed, {
        flow: "setup",
        reason: "passwords_do_not_match",
      });
      notify.warning(
        t("auth.err_password_mismatch_title"),
        t("auth.err_password_mismatch_msg")
      );
      return;
    }

    setIsSubmitting(true);
    trackEvent(
      isSetupMode
        ? MixpanelEvent.Auth_Setup_Started
        : MixpanelEvent.Auth_SignIn_Started,
      {
        username_length: cleanedUsername.length,
      }
    );

    try {
      const response = await fetch(
        getApiUrl(isSetupMode ? "/api/v1/auth/setup" : "/api/v1/auth/login"),
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            username: cleanedUsername,
            password,
          }),
        }
      );

      const payload = await response.json();
      if (!response.ok) {
        const detail = formatFastApiDetail(payload?.detail);
        trackEvent(
          isSetupMode
            ? MixpanelEvent.Auth_Setup_Failed
            : MixpanelEvent.Auth_SignIn_Failed,
          {
            status_code: response.status,
            error_message: sanitizeAnalyticsError(
              detail,
              isSetupMode ? "Could not create account" : "Sign-in failed"
            ),
          }
        );
        if (response.status === 401) {
          notify.error(
            t("auth.err_signin_failed_title"),
            detail === UNAUTHORIZED_DETAIL
              ? t("auth.err_bad_credentials_msg")
              : detail
          );
        } else {
          notify.error(
            isSetupMode ? t("auth.err_create_failed_title") : t("auth.err_signin_failed_title"),
            detail || t("auth.err_generic_msg")
          );
        }
        return;
      }

      if (isSetupMode) {
        trackEvent(MixpanelEvent.Auth_Setup_Completed, {
          username_length: cleanedUsername.length,
        });
        setStatus({
          configured: true,
          authenticated: false,
          username: (payload as AuthStatus).username ?? cleanedUsername,
          role: (payload as AuthStatus).role ?? "admin",
        });
        setPassword("");
        setConfirmPassword("");
        notify.success(t("auth.success_account_created_title"), t("auth.success_account_created_msg"), {
          duration: 6000,
        });
        return;
      }

      setStatus({
        configured: Boolean((payload as AuthStatus).configured),
        authenticated: Boolean((payload as AuthStatus).authenticated),
        username: (payload as AuthStatus).username ?? cleanedUsername,
        role: (payload as AuthStatus).role ?? null,
      });
      trackEvent(MixpanelEvent.Auth_SignIn_Completed, {
        username_length: cleanedUsername.length,
        role: (payload as AuthStatus).role ?? null,
      });
      setPassword("");
      setConfirmPassword("");
      notify.success(
        t("auth.success_signed_in_title"),
        t("auth.success_signed_in_msg")
      );
    } catch (submitError) {
      console.error(submitError);
      trackEvent(
        isSetupMode
          ? MixpanelEvent.Auth_Setup_Failed
          : MixpanelEvent.Auth_SignIn_Failed,
        {
          status_code: null,
          error_message: sanitizeAnalyticsError(
            submitError,
            isSetupMode ? "Could not create account" : "Login unavailable"
          ),
        }
      );
      notify.error(
        t("auth.err_login_unavailable_title"),
        t("auth.err_login_unavailable_msg")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (
    isLoading ||
    isRedirecting ||
    status.authenticated ||
    !hasMetSplashDuration
  ) {
    return <PresentonSplashLoader message={t("auth.splash_message")} />;
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-white p-6 font-syne">
      <section className="relative z-10 w-full max-w-lg rounded-[20px] border border-[#EDEEEF] bg-[#F9F8F8] p-7 sm:p-10">
        <div className="mb-7">
          <div className="flex items-center gap-4">
            <div className="flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-[4px] bg-[#F4F3FF] p-3">
              <Image
                src="/logo-with-bg.png"
                alt=""
                width={161}
                height={166}
                className="h-10 w-auto object-contain"
              />
            </div>
            <div>
              <p className="font-syne text-[10px] font-semibold uppercase tracking-[0.14em] text-[#7A5AF8]">
                {t("auth.secure_instance")}
              </p>
              <h1 className="mt-1 font-syne text-xl font-normal leading-tight tracking-[-0.03em] text-black sm:text-[22px]">
                {isSetupMode ? t("auth.create_admin_login") : t("auth.sign_in_to_continue")}
              </h1>
            </div>
          </div>
        </div>

        <p className="max-w-md text-sm leading-relaxed text-[#6B7280]">
          {isSetupMode
            ? t("auth.setup_desc")
            : t("auth.protected_desc")}
        </p>

        <form onSubmit={handleSubmit} className="mt-7 space-y-5">
          <div className="space-y-2">
            <label htmlFor="username" className="block text-sm font-medium text-[#374151]">
              {t("auth.username")}
            </label>
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(event) =>
                setUsername(event.target.value.replace(/\s/g, ""))
              }
              placeholder={t("auth.username_placeholder")}
              minLength={3}
              maxLength={128}
              pattern="\S+"
              title={t("auth.username_placeholder")}
              required
              spellCheck={false}
              className="h-12 w-full rounded-lg border border-[#E1E1E5] bg-white px-4 text-sm text-[#191919] outline-none transition placeholder:text-[#9CA3AF] focus:border-[#7A5AF8] focus:ring-2 focus:ring-[#7A5AF8]/15"
              disabled={isSubmitting}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="password" className="block text-sm font-medium text-[#374151]">
              {t("auth.password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete={isSetupMode ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={
                isSetupMode ? t("auth.password_placeholder_setup") : t("auth.password_placeholder_signin")
              }
              minLength={isSetupMode ? 8 : 6}
              maxLength={128}
              required
              className="h-12 w-full rounded-lg border border-[#E1E1E5] bg-white px-4 text-sm text-[#191919] outline-none transition placeholder:text-[#9CA3AF] focus:border-[#7A5AF8] focus:ring-2 focus:ring-[#7A5AF8]/15"
              disabled={isSubmitting}
            />
          </div>

          {isSetupMode ? (
            <div className="space-y-2">
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-[#374151]">
                {t("auth.confirm_password")}
              </label>
              <input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder={t("auth.confirm_password_placeholder")}
                minLength={8}
                maxLength={128}
                required
                className="h-12 w-full rounded-lg border border-[#E1E1E5] bg-white px-4 text-sm text-[#191919] outline-none transition placeholder:text-[#9CA3AF] focus:border-[#7A5AF8] focus:ring-2 focus:ring-[#7A5AF8]/15"
                disabled={isSubmitting}
              />
            </div>
          ) : null}

          {!isSetupMode && status.configured ? (
            <p className="rounded-lg border border-[#EDEEEF] bg-white px-4 py-3 text-xs leading-relaxed text-[#6B7280]">
              {t("auth.admin_hint")}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-[58px] border border-[#EDEEEF] bg-[#7C51F8] px-5 py-3 font-syne text-xs font-semibold text-white transition hover:bg-[#6d46e6] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting
              ? isSetupMode
                ? t("auth.btn_saving")
                : t("auth.btn_signing_in")
              : isSetupMode
                ? t("auth.btn_create_account")
                : t("auth.btn_sign_in")}
          </button>
        </form>

        {oidcLoginEnabled ? (
          <div className="mt-7">
            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-[#EDEEEF]" />
              <span className="text-xs font-medium uppercase tracking-wide text-[#9CA3AF]">
                {t("common.or")}
              </span>
              <span className="h-px flex-1 bg-[#EDEEEF]" />
            </div>
            <a
              href={getApiUrl("/api/v1/auth/oidc/login")}
              onClick={() => {
                trackEvent(MixpanelEvent.Auth_SignIn_Started, { method: "oidc" });
              }}
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-[58px] border border-[#E1E1E5] bg-white px-5 py-3 font-syne text-xs font-semibold text-[#374151] transition hover:border-[#7A5AF8] hover:text-[#7A5AF8]"
            >
              {oidcLoginLabel ?? t("auth.oidc_default_label")}
            </a>
          </div>
        ) : null}
      </section>
    </main>
  );
}
