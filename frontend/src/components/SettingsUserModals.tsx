import type React from 'react';
import { Edit2, Key, Loader2, RotateCcw, Save, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { checkPasswordComplexity } from '../utils/password';
import { Button } from './Button';
import { Card, CardContent, CardHeader } from './Card';

export interface UserFormState {
  username: string;
  password?: string;
  email?: string;
  confirmPassword: string;
  role: string;
  group_ids: number[];
}

export interface GroupSummary {
  id: number;
  name: string;
  is_system?: boolean;
}

export interface DeleteUserCounts {
  archives: number;
  queue_items: number;
  library_files: number;
}

export interface ChangePasswordState {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

interface SettingsUserModalsProps {
  showEditUserModal: boolean;
  editingUserId: number | null;
  setShowEditUserModal: (v: boolean) => void;
  setEditingUserId: (id: number | null) => void;
  userFormData: UserFormState;
  setUserFormData: React.Dispatch<React.SetStateAction<UserFormState>>;
  advancedAuthEnabled: boolean;
  groupsData: GroupSummary[];
  toggleUserGroup: (groupId: number) => void;
  handleUpdateUser: (userId: number) => void;
  updateUserPending: boolean;
  resetPasswordPending: boolean;
  onResetPassword: (userId: number) => void;
  deleteUserId: number | null;
  setDeleteUserId: (id: number | null) => void;
  deleteUserItemCounts: DeleteUserCounts | null;
  setDeleteUserItemCounts: (counts: DeleteUserCounts | null) => void;
  deleteUserLoading: boolean;
  deleteUserPending: boolean;
  onDeleteUser: (args: { id: number; deleteItems: boolean }) => void;
  showChangePasswordModal: boolean;
  setShowChangePasswordModal: (v: boolean) => void;
  changePasswordData: ChangePasswordState;
  setChangePasswordData: React.Dispatch<React.SetStateAction<ChangePasswordState>>;
  changePasswordLoading: boolean;
  setChangePasswordLoading: (v: boolean) => void;
  showToast: (msg: string, type?: 'success' | 'error') => void;
}

export function SettingsUserModals({
  showEditUserModal,
  editingUserId,
  setShowEditUserModal,
  setEditingUserId,
  userFormData,
  setUserFormData,
  advancedAuthEnabled,
  groupsData,
  toggleUserGroup,
  handleUpdateUser,
  updateUserPending,
  resetPasswordPending,
  onResetPassword,
  deleteUserId,
  setDeleteUserId,
  deleteUserItemCounts,
  setDeleteUserItemCounts,
  deleteUserLoading,
  deleteUserPending,
  onDeleteUser,
  showChangePasswordModal,
  setShowChangePasswordModal,
  changePasswordData,
  setChangePasswordData,
  changePasswordLoading,
  setChangePasswordLoading,
  showToast,
}: SettingsUserModalsProps) {
  const { t } = useTranslation();

  const resetUserForm = () => {
    setUserFormData({
      username: '',
      password: '',
      email: '',
      confirmPassword: '',
      role: 'user',
      group_ids: [],
    });
  };

  return (
    <>
      {showEditUserModal && editingUserId !== null && (
        <div
          className="fixed inset-0 bg-black flex items-center justify-center z-50 p-4"
          onClick={() => {
            setShowEditUserModal(false);
            setEditingUserId(null);
            resetUserForm();
          }}
        >
          <Card
            className="w-full max-w-md"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          >
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Edit2 className="w-5 h-5 text-bambu-green" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{t('settings.editUser')}</h2>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowEditUserModal(false);
                    setEditingUserId(null);
                    resetUserForm();
                  }}
                >
                  <X className="w-5 h-5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                    {t('settings.username')} {advancedAuthEnabled && <span className="text-red-700 dark:text-red-400">*</span>}
                  </label>
                  <input
                    type="text"
                    value={userFormData.username}
                    onChange={(e) => setUserFormData({ ...userFormData, username: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('settings.enterUsername')}
                    autoComplete="username"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                    {t('users.form.email') || 'Email'} {advancedAuthEnabled ? <span className="text-red-700 dark:text-red-400">*</span> : <span className="text-bambu-gray font-normal">({t('users.form.optional') || 'optional'})</span>}
                  </label>
                  <input
                    type="email"
                    value={userFormData.email}
                    onChange={(e) => setUserFormData({ ...userFormData, email: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('users.form.emailPlaceholder') || 'user@example.com'}
                    required={advancedAuthEnabled}
                  />
                </div>

                {!advancedAuthEnabled && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                        {t('users.form.password') || 'Password'} <span className="text-bambu-gray font-normal">({t('users.form.leaveBlankToKeep') || 'leave blank to keep current'})</span>
                      </label>
                      <input
                        type="password"
                        value={userFormData.password}
                        onChange={(e) => setUserFormData({ ...userFormData, password: e.target.value, confirmPassword: '' })}
                        className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                        placeholder={t('settings.enterNewPassword')}
                        autoComplete="new-password"
                        minLength={8}
                      />
                      <p className="text-bambu-gray text-xs mt-1">{t('settings.passwordRequirements')}</p>
                    </div>
                    {userFormData.password && (
                      <div>
                        <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">{t('settings.confirmPassword')}</label>
                        <input
                          type="password"
                          value={userFormData.confirmPassword}
                          onChange={(e) => setUserFormData({ ...userFormData, confirmPassword: e.target.value })}
                          className={`w-full px-4 py-3 bg-bambu-dark-secondary border rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors ${
                            userFormData.confirmPassword && userFormData.password !== userFormData.confirmPassword
                              ? 'border-red-500'
                              : 'border-bambu-dark-tertiary'
                          }`}
                          placeholder={t('settings.confirmNewPassword')}
                          autoComplete="new-password"
                          minLength={6}
                        />
                        {userFormData.confirmPassword && userFormData.password !== userFormData.confirmPassword && (
                          <p className="text-red-700 dark:text-red-400 text-xs mt-1">{t('settings.passwordsDoNotMatch')}</p>
                        )}
                      </div>
                    )}
                  </>
                )}

                {advancedAuthEnabled && (
                  <div className="bg-bambu-dark-secondary/50 border border-bambu-green/20 rounded-lg p-3 space-y-3">
                    <p className="text-sm text-bambu-gray">
                      {t('users.form.passwordManagedByAdvancedAuth') || 'Password is managed by Advanced Authentication. Use "Reset Password" to send a new password to the user via email.'}
                    </p>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => editingUserId && onResetPassword(editingUserId)}
                      disabled={resetPasswordPending || !userFormData.email}
                      className="w-full"
                    >
                      {resetPasswordPending ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          {t('users.form.resettingPassword') || 'Resetting Password...'}
                        </>
                      ) : (
                        <>
                          <RotateCcw className="w-4 h-4" />
                          {t('users.form.resetPassword') || 'Reset Password'}
                        </>
                      )}
                    </Button>
                  </div>
                )}

                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">{t('users.form.groups') || 'Groups'}</label>
                  <div className="space-y-2 max-h-40 overflow-y-auto p-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg">
                    {groupsData.map(group => (
                      <label
                        key={group.id}
                        className="flex items-center gap-3 px-2 py-1.5 rounded hover:bg-bambu-dark-tertiary cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={userFormData.group_ids.includes(group.id)}
                          onChange={() => toggleUserGroup(group.id)}
                          className="w-4 h-4 rounded border-bambu-gray text-bambu-green focus:ring-bambu-green focus:ring-offset-0 bg-bambu-dark"
                        />
                        <span className="text-sm text-gray-900 dark:text-white">{group.name}</span>
                        {group.is_system && (
                          <span className="text-xs text-yellow-700 dark:text-yellow-400">({t('users.system') || 'System'})</span>
                        )}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowEditUserModal(false);
                    setEditingUserId(null);
                    resetUserForm();
                  }}
                >
                  {t('users.modal.cancel') || 'Cancel'}
                </Button>
                <Button
                  onClick={() => handleUpdateUser(editingUserId)}
                  disabled={
                    updateUserPending ||
                    !userFormData.username ||
                    (advancedAuthEnabled && !userFormData.email) ||
                    Boolean(!advancedAuthEnabled && userFormData.password && (userFormData.password !== userFormData.confirmPassword || checkPasswordComplexity(userFormData.password) !== null))
                  }
                >
                  {updateUserPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {t('users.modal.saving') || 'Saving...'}
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      {t('users.modal.saveChanges') || 'Save Changes'}
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {deleteUserId !== null && (
        <div
          className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
          onClick={() => {
            setDeleteUserId(null);
            setDeleteUserItemCounts(null);
          }}
        >
          <Card
            className="w-full max-w-md"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          >
            <CardHeader>
              <div className="flex items-center gap-2 text-red-700 dark:text-red-400">
                <Trash2 className="w-5 h-5" />
                <h3 className="text-lg font-semibold">{t('settings.deleteUserTitle')}</h3>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {deleteUserLoading ? (
                <div className="flex items-center justify-center py-4">
                  <div className="animate-spin rounded-full h-6 w-6 border-2 border-bambu-green border-t-transparent" />
                </div>
              ) : deleteUserItemCounts && (deleteUserItemCounts.archives + deleteUserItemCounts.queue_items + deleteUserItemCounts.library_files > 0) ? (
                <>
                  <p className="text-gray-900 dark:text-white">{t('settings.userHasCreated')}</p>
                  <ul className="list-disc list-inside text-bambu-gray space-y-1">
                    {deleteUserItemCounts.archives > 0 && (
                      <li>{deleteUserItemCounts.archives} archive{deleteUserItemCounts.archives !== 1 ? 's' : ''}</li>
                    )}
                    {deleteUserItemCounts.queue_items > 0 && (
                      <li>{deleteUserItemCounts.queue_items} queue item{deleteUserItemCounts.queue_items !== 1 ? 's' : ''}</li>
                    )}
                    {deleteUserItemCounts.library_files > 0 && (
                      <li>{deleteUserItemCounts.library_files} library file{deleteUserItemCounts.library_files !== 1 ? 's' : ''}</li>
                    )}
                  </ul>
                  <p className="text-bambu-gray text-sm">{t('settings.userItemsQuestion')}</p>
                  <div className="flex flex-col gap-2">
                    <Button
                      variant="danger"
                      onClick={() => onDeleteUser({ id: deleteUserId, deleteItems: true })}
                      disabled={deleteUserPending}
                      className="justify-center"
                    >
                      {t('settings.deleteUserAndItems')}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => onDeleteUser({ id: deleteUserId, deleteItems: false })}
                      disabled={deleteUserPending}
                      className="justify-center"
                    >
                      {t('settings.deleteUserKeepItems')}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setDeleteUserId(null);
                        setDeleteUserItemCounts(null);
                      }}
                      disabled={deleteUserPending}
                      className="justify-center"
                    >
                      {t('common.cancel')}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="text-gray-900 dark:text-white">{t('settings.deleteUserConfirm')}</p>
                  <p className="text-bambu-gray text-sm">{t('settings.actionCannotBeUndone')}</p>
                  <div className="flex gap-2 justify-end">
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setDeleteUserId(null);
                        setDeleteUserItemCounts(null);
                      }}
                      disabled={deleteUserPending}
                    >
                      {t('common.cancel')}
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => onDeleteUser({ id: deleteUserId, deleteItems: false })}
                      disabled={deleteUserPending}
                    >
                      {t('settings.deleteUserTitle')}
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {showChangePasswordModal && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
          onClick={() => {
            setShowChangePasswordModal(false);
            setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
          }}
        >
          <Card
            className="w-full max-w-md"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          >
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key className="w-5 h-5 text-bambu-green" />
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{t('settings.changePassword')}</h2>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowChangePasswordModal(false);
                    setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                  }}
                >
                  <X className="w-5 h-5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                    Current Password
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.currentPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, currentPassword: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('settings.enterCurrentPassword')}
                    autoComplete="current-password"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                    New Password
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.newPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, newPassword: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('settings.enterNewPasswordMin6')}
                    autoComplete="new-password"
                    minLength={6}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-900 dark:text-white mb-2">
                    Confirm New Password
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.confirmPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, confirmPassword: e.target.value })}
                    className={`w-full px-4 py-3 bg-bambu-dark-secondary border rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors ${
                      changePasswordData.confirmPassword && changePasswordData.newPassword !== changePasswordData.confirmPassword
                        ? 'border-red-500'
                        : 'border-bambu-dark-tertiary'
                    }`}
                    placeholder={t('settings.confirmNewPassword')}
                    autoComplete="new-password"
                    minLength={6}
                  />
                  {changePasswordData.confirmPassword && changePasswordData.newPassword !== changePasswordData.confirmPassword && (
                    <p className="text-red-700 dark:text-red-400 text-xs mt-1">{t('settings.passwordsDoNotMatch')}</p>
                  )}
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowChangePasswordModal(false);
                    setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                  }}
                >
                  {t('common.cancel')}
                </Button>
                <Button
                  onClick={async () => {
                    if (changePasswordData.newPassword !== changePasswordData.confirmPassword) {
                      showToast(t('settings.toast.passwordsDoNotMatch'), 'error');
                      return;
                    }
                    if (changePasswordData.newPassword.length < 6) {
                      showToast(t('settings.toast.passwordTooShort'), 'error');
                      return;
                    }
                    setChangePasswordLoading(true);
                    try {
                      await api.changePassword(changePasswordData.currentPassword, changePasswordData.newPassword);
                      showToast(t('settings.toast.passwordChanged'), 'success');
                      setShowChangePasswordModal(false);
                      setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                    } catch (error: unknown) {
                      const message = error instanceof Error ? error.message : 'Failed to change password';
                      showToast(message, 'error');
                    } finally {
                      setChangePasswordLoading(false);
                    }
                  }}
                  disabled={changePasswordLoading || !changePasswordData.currentPassword || !changePasswordData.newPassword || changePasswordData.newPassword !== changePasswordData.confirmPassword || changePasswordData.newPassword.length < 6}
                >
                  {changePasswordLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {t('settings.changing')}
                    </>
                  ) : (
                    <>
                      <Key className="w-4 h-4" />
                      {t('settings.changePassword')}
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
