export interface LeadSortable {
  isUserAdded?: boolean;
  created_at?: string;
}

/** User-added leads (manual / Excel) first, then newest within each group. */
export function sortLeadsWithUserAddedFirst<T extends LeadSortable>(leads: T[]): T[] {
  return [...leads].sort((a, b) => {
    const aUserAdded = !!a.isUserAdded;
    const bUserAdded = !!b.isUserAdded;
    if (aUserAdded !== bUserAdded) {
      return aUserAdded ? -1 : 1;
    }
    if (!a.created_at && !b.created_at) return 0;
    if (!a.created_at) return 1;
    if (!b.created_at) return -1;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

export interface CampaignLeadSortable {
  is_user_added?: boolean;
  created_at?: string;
}

export function sortCampaignLeadsWithUserAddedFirst<T extends CampaignLeadSortable>(leads: T[]): T[] {
  return [...leads].sort((a, b) => {
    const aUserAdded = !!a.is_user_added;
    const bUserAdded = !!b.is_user_added;
    if (aUserAdded !== bUserAdded) {
      return aUserAdded ? -1 : 1;
    }
    if (!a.created_at && !b.created_at) return 0;
    if (!a.created_at) return 1;
    if (!b.created_at) return -1;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}
