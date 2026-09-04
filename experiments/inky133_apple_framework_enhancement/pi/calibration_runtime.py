"""Runtime state for temporary Color Calibration display."""

from __future__ import annotations

import logging
import threading

from PIL import Image

try:
    from .color_calibration import (
        CalibrationError,
        CalibrationState,
        ColorCalibrationCatalog,
        compose_calibration_image,
    )
except ImportError:
    from color_calibration import (
        CalibrationError,
        CalibrationState,
        ColorCalibrationCatalog,
        compose_calibration_image,
    )


logger = logging.getLogger("inky133_apple_effects")


class CalibrationSession:
    def __init__(self, display, catalog: ColorCalibrationCatalog, *, font_path: str) -> None:
        self.display = display
        self.catalog = catalog
        self.font_path = font_path
        self.state = CalibrationState()
        self.current_prepared: Image.Image | None = None
        self.target_index: int | None = None
        self.lock = threading.Lock()

    def show_normal(self, _entry, prepared: Image.Image) -> None:
        with self.lock:
            self.state.exit()
            self.current_prepared = prepared.copy()
            self.target_index = None
            self.display.set_image(prepared)
            self.display.show()

    def clear_for_next(self) -> None:
        with self.lock:
            self.state.exit()
            self.target_index = None

    def is_active(self) -> bool:
        with self.lock:
            return self.state.active

    def _show_calibration_locked(self) -> bool:
        if not self.state.active or self.state.source is None:
            return False
        assets = self.catalog.lookup(self.state.source)
        if assets is None:
            logger.warning(
                "Color calibration unavailable: source=%s",
                self.state.source,
            )
            self.state.exit()
            self.target_index = None
            return False
        prepared = compose_calibration_image(
            assets,
            self.state,
            font_path=self.font_path,
        )
        logger.info(
            "Color calibration display: source=%s pattern=P%d strength=%s",
            self.state.source,
            self.state.pattern_number,
            self.state.strength,
        )
        self.display.set_image(prepared)
        self.display.show()
        logger.info("Color calibration display completed")
        return True

    def c_short(self) -> None:
        with self.lock:
            if self.current_prepared is None:
                logger.info("Color calibration ignored: no normal image to restore")
                return
            if len(self.catalog) == 0:
                logger.warning("Color calibration ignored: manifest has no targets")
                return
            if self.state.active:
                assert self.target_index is not None
                self.target_index = (self.target_index + 1) % len(self.catalog)
                assets = self.catalog.at(self.target_index)
                self.state.select_source(assets.source)
                if self.state.sat_comparison and not assets.supports_sat_comparison:
                    self.state.exit_sat_comparison()
                    logger.warning(
                        "Color calibration comparison mode reset to STANDARD: "
                        "extended SAT assets missing for source=%s",
                        assets.source,
                    )
                logger.info(
                    "Color calibration target: %d/%d source=%s",
                    self.target_index + 1,
                    len(self.catalog),
                    assets.source,
                )
            else:
                self.target_index = 0
                assets = self.catalog.at(self.target_index)
                self.state.enter(assets.source)
                logger.info(
                    "Color calibration entered: target=1/%d source=%s",
                    len(self.catalog),
                    assets.source,
                )
            try:
                self._show_calibration_locked()
            except CalibrationError:
                logger.exception("Color calibration render failed")
                self.state.exit()
                self.target_index = None

    def c_long(self) -> None:
        with self.lock:
            if not self.state.active:
                logger.info("Color calibration exit ignored: mode is off")
                return
            self.state.exit()
            self.target_index = None
            logger.info("Color calibration exited")
            if self.current_prepared is not None:
                self.display.set_image(self.current_prepared.copy())
                self.display.show()
                logger.info("Normal image restored after calibration")

    def d_short(self) -> None:
        with self.lock:
            if not self.state.active:
                logger.info("Color calibration strength ignored: mode is off")
                return
            if self.state.sat_comparison:
                self.state.next_sat_group()
                logger.info(
                    "Color calibration SAT group: %d",
                    self.state.sat_group_index + 1,
                )
            else:
                self.state.next_strength()
                logger.info("Color calibration strength: %s", self.state.strength)
            try:
                self._show_calibration_locked()
            except CalibrationError:
                logger.exception("Color calibration render failed")
                self.state.exit()
                self.target_index = None

    def d_long(self) -> None:
        with self.lock:
            if not self.state.active or self.state.source is None:
                logger.info("Color calibration SAT mode ignored: mode is off")
                return
            assets = self.catalog.lookup(self.state.source)
            if assets is None:
                logger.warning(
                    "Color calibration SAT mode unavailable: source=%s",
                    self.state.source,
                )
                return
            if self.state.sat_comparison:
                self.state.exit_sat_comparison()
                logger.info("Color calibration comparison mode: STANDARD")
            else:
                if not assets.supports_sat_comparison:
                    logger.warning(
                        "Color calibration extended SAT assets missing: source=%s",
                        self.state.source,
                    )
                    return
                self.state.enter_sat_comparison()
                logger.info("Color calibration comparison mode: SAT")
            try:
                self._show_calibration_locked()
            except CalibrationError:
                logger.exception("Color calibration render failed")
                self.state.exit()
                self.target_index = None
