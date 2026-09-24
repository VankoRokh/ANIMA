from anima.core.state import AnimaState


def main():
    anima = AnimaState()

    anima.wake()

    state = anima.get()

    print()
    print("=" * 40)
    print(f"{state['name']} {state['version']}")
    print("=" * 40)
    print(f"Status:           {state['status']}")
    print(f"Session:          {state['session']}")
    print(f"Created:          {state['created_at']}")
    print(f"Last wake:        {state['last_wake']}")
    print(f"Events processed: {state['events_processed']}")
    print("=" * 40)
    print()

    input("Press Enter to put ANIMA to sleep...")

    anima.sleep()

    print("ANIMA is sleeping.")


if __name__ == "__main__":
    main()
