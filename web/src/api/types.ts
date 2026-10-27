import type {
  DuplicateSubmission,
  ItemDetail,
  ItemOrganization,
  ItemType,
  QueuedSubmission,
  RejectedSubmission,
} from "./schema.gen";

export type {
  BriefPointView as BriefPoint,
  BriefState,
  BriefView as Brief,
  CitationView as Citation,
  Decision,
  DigestGroup,
  DigestHeader,
  DigestLine,
  DigestPick,
  DigestsView,
  DigestView as Digest,
  Estimate,
  GoalCategory,
  GoalCreate,
  GoalDraft,
  GoalPatch,
  GoalView as Goal,
  Hold,
  ImportAction,
  ImportPhase,
  ImportView as Import,
  ItemDetail,
  ItemMotion,
  ItemOrganization,
  ItemRef,
  ItemStatus,
  ItemSummary as Item,
  ItemType,
  LabelCount,
  MergeSuggestion,
  NavCounts,
  Notice,
  PauseReason,
  QuestionKind,
  SetupAnswer,
  SetupApply,
  SetupPlan,
  SetupQuestion,
  SetupView,
  Source,
  SourceView as BriefSource,
  Stage,
  StatusView as Status,
  TopicDetail,
  TopicRef,
  TopicSummary as Topic,
  TopicsView,
  UserAction,
} from "./schema.gen";

export type Submission = QueuedSubmission | DuplicateSubmission | RejectedSubmission;

export type Card = NonNullable<ItemDetail["card"]>;
export type CardOf<T extends ItemType> = Extract<Card, { item_type: T }>;

export type TopicChooser = NonNullable<ItemOrganization["topic_chosen_by"]>;

export {
  goalCategoryValues as GOAL_CATEGORIES,
  itemTypeValues as ITEM_TYPES,
  stageValues as STAGES,
} from "./schema.gen";
