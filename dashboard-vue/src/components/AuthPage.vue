<template>
  <main class="auth-page">
    <section class="auth-card">
      <header class="auth-header">
        <img src="https://images.juniorbay.com/icon/favicon.png" alt="" />
        <h1>Admin Login</h1>
        <p>Enter your credentials to access the admin panel</p>
      </header>

      <div class="auth-body">
        <div class="auth-tabs">
          <button type="button" :class="{ active: store.activeTab === 'login' }" @click="store.setTab('login')">Login</button>
          <button type="button" :class="{ active: store.activeTab === 'register' }" @click="store.setTab('register')">Register</button>
          <button type="button" :class="{ active: store.activeTab === 'forgot' }" @click="store.setTab('forgot')">Forgot</button>
        </div>

        <form v-if="store.activeTab === 'login'" class="auth-form" @submit.prevent="store.login">
          <label>Email<input v-model.trim="store.loginForm.email" type="email" placeholder="admin@example.com" autocomplete="username" required /></label>
          <label>Password<input v-model="store.loginForm.password" type="password" placeholder="Enter your password" autocomplete="current-password" required /></label>
          <button class="primary-action stretch" type="submit" :disabled="store.loading">{{ store.loading ? "Signing In..." : "Sign In" }}</button>
        </form>

        <div v-else-if="store.activeTab === 'register'" class="auth-form-stack">
          <form class="auth-form" @submit.prevent="store.register">
            <label>First Name<input v-model.trim="store.registerForm.first_name" placeholder="John" autocomplete="given-name" required /></label>
            <label>Last Name<input v-model.trim="store.registerForm.last_name" placeholder="Doe" autocomplete="family-name" required /></label>
            <label>Email<input v-model.trim="store.registerForm.email" type="email" placeholder="john@example.com" autocomplete="email" required /></label>
            <label>Phone Number<input v-model.trim="store.registerForm.phone_number" type="tel" placeholder="+1234567890" autocomplete="tel" /></label>
            <span class="field-note">Format: +1234567890 (include country code)</span>
            <label>Password<input v-model="store.registerForm.password" type="password" placeholder="Create a password" autocomplete="new-password" required /></label>
            <button class="primary-action stretch" type="submit" :disabled="store.loading">{{ store.loading ? "Creating..." : "Create Account" }}</button>
          </form>

          <div class="info-toast">After sign-up, check your email for the verification code.</div>

          <form class="auth-form" @submit.prevent="store.confirm">
            <h2>Confirm Email</h2>
            <label>Email<input v-model.trim="store.confirmForm.email" type="email" autocomplete="email" required /></label>
            <label>Verification Code<input v-model.trim="store.confirmForm.code" inputmode="numeric" required /></label>
            <button class="primary-action" type="submit" :disabled="store.loading">Confirm Email</button>
          </form>
        </div>

        <div v-else class="auth-form-stack">
          <form class="auth-form" @submit.prevent="store.forgotPassword">
            <h2>Reset Password</h2>
            <label>Email<input v-model.trim="store.forgotForm.email" type="email" placeholder="Enter your email" autocomplete="email" required /></label>
            <button class="primary-action stretch" type="submit" :disabled="store.loading">Send Reset Code</button>
          </form>

          <form class="auth-form" @submit.prevent="store.resetPassword">
            <h2>Confirm New Password</h2>
            <label>Email<input v-model.trim="store.resetForm.email" type="email" autocomplete="email" required /></label>
            <label>Code<input v-model.trim="store.resetForm.code" inputmode="numeric" required /></label>
            <label>New Password<input v-model="store.resetForm.new_password" type="password" autocomplete="new-password" required /></label>
            <button class="primary-action" type="submit" :disabled="store.loading">Set New Password</button>
          </form>
        </div>

        <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
        <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { useAuthStore } from "../stores/auth";

const store = useAuthStore();
</script>
