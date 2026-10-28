import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { SetupPage } from '../../pages/SetupPage';

function useStatus(authRequired: boolean) {
  server.use(
    http.get('*/api/v1/auth/status', () =>
      HttpResponse.json({ auth_enabled: false, requires_setup: true, auth_required: authRequired }),
    ),
  );
}

describe('SetupPage', () => {
  it('lets you choose whether to enable authentication by default', async () => {
    useStatus(false);
    render(<SetupPage />);
    const box = await screen.findByRole('checkbox');
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    expect(screen.queryByText(/mandatory for this installation/i)).not.toBeInTheDocument();
    await userEvent.click(box);
    expect(box).toBeChecked();
  });

  it('forces authentication when the server requires it', async () => {
    useStatus(true);
    render(<SetupPage />);
    await screen.findByText(/mandatory for this installation/i);
    const box = screen.getByRole('checkbox');
    await waitFor(() => expect(box).toBeChecked());
    expect(box).toBeDisabled();
    expect(screen.getByLabelText(/password/i, { selector: 'input[type="password"]' })).toBeInTheDocument();
  });
});
