import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../utils';
import { PushNotificationsCard } from '../../components/PushNotificationsCard';

describe('PushNotificationsCard', () => {
  it('explains that this browser cannot receive notifications', async () => {
    render(<PushNotificationsCard />);
    expect(await screen.findByTestId('push-notifications-card')).toBeInTheDocument();
    expect(screen.getByText('Browser notifications')).toBeInTheDocument();
    // jsdom kennt weder PushManager noch einen sicheren Kontext.
    expect(screen.getByText(/cannot receive notifications/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Turn on' })).not.toBeInTheDocument();
  });
});
