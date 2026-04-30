import torch
import time
from typing import Optional
from decimal import Decimal


class PlotA():
    def __init__(self, plot_width: int, plot_height: int, *,
                spread: Optional[Decimal] = None,
                price_min: Optional[Decimal] = None,
                price_max: Optional[Decimal] = None,
                history_max_seconds: Optional[int] = 604800, # default to 1 week of seconds
                **kwargs):
        """
        Initializing the PlotA class will construct a H = (B, W, 2) tensor to hold the bid and asks for a specified 'history window'.
        In this matrix, each column corresponds to a unique timestamp of seconds. Each row corresponds to a price level determined by the spread.

        This structure will likely not match the plot dimensions and a matrix multiplication step is likely needed to fit the plot dimensions of (plot_width, plot_height).
        """
        assert (int(plot_width) > 0) and (int(plot_height) > 0) and (int(history_max_seconds) > 0), "plot_width, plot_height, and history_max_seconds must be positive integers."

        assert isinstance(plot_width, int) and plot_width > 0
        assert isinstance(plot_height, int) and plot_height > 0
        assert isinstance(history_max_seconds, int) and history_max_seconds > 0

        if spread is not None:
            assert isinstance(spread, Decimal), "spread must be a Decimal"
        if price_min is not None:
            assert isinstance(price_min, Decimal), "price_min must be a Decimal"
        if price_max is not None:
            assert isinstance(price_max, Decimal), "price_max must be a Decimal"

        self.spread = spread
        self.price_min = price_min
        self.price_max = price_max

        if self.spread is not None and self.price_min is not None and self.price_max is not None:
            # print(self.price_min, self.spread)
            assert self.price_min % self.spread == 0
            assert self.price_max % self.spread == 0
            self._generate_column_template()
            self.H = torch.zeros((len(self.column_template), history_max_seconds, 2)) # (B, W, 2) tensor to hold bid and ask data

    def _grab_history_section(
        self,
        end_epoch: int,
        start_epoch: Optional[int] = None,
        lowest_price: Optional[Decimal] = None,
        highest_price: Optional[Decimal] = None,
        now_epoch: Optional[int] = None,
    ):
        """
        Returns:
        section: Tensor shaped (B_active, T, 2)
        price_range: (low_price, high_price) as Decimals in original H price space
        timestamp_range: (start_ts, end_ts) as epoch-second ints in original H time space
        """
        if not hasattr(self, "H") or self.H is None:
            raise ValueError("H is not initialized")

        current_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
        if start_epoch is None:
            start_epoch = current_epoch

        # Map time domain into H columns
        c_end = self.time_to_idx(int(end_epoch), now_epoch=current_epoch)
        c_start = self.time_to_idx(int(start_epoch), now_epoch=current_epoch)
        if c_end is None or c_start is None:
            raise ValueError("Requested time range is outside history window")

        c0, c1 = sorted((c_end, c_start))
        time_slice = self.H[:, c0:c1 + 1, :]  # (B, T, 2)

        # Optional explicit price-domain clamp first
        if lowest_price is not None or highest_price is not None:
            lo = 0 if lowest_price is None else self.price_to_idx(lowest_price)
            hi = (self.H.shape[0] - 1) if highest_price is None else self.price_to_idx(highest_price)
            r_lo, r_hi = sorted((lo, hi))
            r_lo = max(0, r_lo)
            r_hi = min(self.H.shape[0] - 1, r_hi)
            base_row_offset = r_lo
            time_slice = time_slice[r_lo:r_hi + 1, :, :]
        else:
            base_row_offset = 0

        # Find active rows in this time domain
        # row_score shape: (B_slice,)
        row_score = time_slice.abs().sum(dim=(1, 2))
        active = row_score > 0
        nz = torch.nonzero(active, as_tuple=False).squeeze(1)

        if nz.numel() == 0:
            # no active rows in the requested domain
            empty = time_slice[:0, :, :]
            ts_start = self.idx_to_time(c0, now_epoch=current_epoch)
            ts_end = self.idx_to_time(c1, now_epoch=current_epoch)
            return empty, (None, None), (ts_start, ts_end)

        local_r0 = int(nz.min().item())
        local_r1 = int(nz.max().item())

        section = time_slice[local_r0:local_r1 + 1, :, :]
        r0 = base_row_offset + local_r0
        r1 = base_row_offset + local_r1
        price_low = self.idx_to_price(r0)
        price_high = self.idx_to_price(r1)
        ts_start = self.idx_to_time(c0, now_epoch=current_epoch)
        ts_end = self.idx_to_time(c1, now_epoch=current_epoch)
        return section, (price_low, price_high), (ts_start, ts_end)




    """
    In order to push new data, the plot needs to know how to map incoming price levels to the appropriate indices in the column template. The price_to_idx function serves this
    purpose by converting a given price into its corresponding index based on the defined spread and minimum price. This mapping is crucial for efficiently updating the plot with
    new data, as it allows the system to quickly determine where to place incoming information within the existing structure of the plot, ensuring that updates are accurate and
    visually coherent.
    """
    def _generate_column_template(self):
        """
        Generates a column template based on the current plot settings. This template serves as a blueprint for how data will be organized and displayed on the plot. By defining
        a clear structure for the columns, the plot can efficiently manage and render incoming data, ensuring that it is presented in a coherent and visually appealing manner.
        """
        assert self.spread and self.price_min and self.price_max, "spread, price_min, and price_max must be set to generate column template."

        # Create column template of zeros with indices corresponding to price levels based on price_min, price_max, and spread.
        # The number of rows is determined by the range of prices divided by the spread, and the number of columns is determined
        # by the plot width and price density.
        #
        # Torch does not support Decimal, so we need to convert to integers by scaling the price levels and spread appropriately.
        scale = Decimal("1") / Decimal(self.spread)
        start = self.price_min * scale
        step = Decimal("1")
        end = self.price_max * scale + step
        self.column_template = torch.zeros(len(torch.arange(int(start), int(end), int(step))))
        self.column_template = self.column_template.t()

        return self.column_template

    def price_to_idx(self, price: Decimal) -> int:
        k = (price - self.price_min) / self.spread
        if k != k.to_integral_value():
            raise ValueError("price is off-grid")
        return int(k)

    def time_to_idx(self, time_epoch: int, now_epoch: int | None = None) -> int | None:
        if not hasattr(self, "H") or self.H is None:
            raise ValueError("H is not initialized")

        now = int(time.time()) if now_epoch is None else int(now_epoch)
        event = int(time_epoch)
        dt = now - event  # seconds ago

        if dt < 0:
            return None  # future timestamp

        width = int(self.H.shape[1])  # history window in seconds
        idx = (width - 1) - dt        # rightmost is "now"

        if idx < 0 or idx >= width:
            return None  # outside stored history window

        return idx

    def idx_to_price(self, idx: int) -> Decimal:
        if self.price_min is None or self.spread is None:
            raise ValueError("price_min and spread must be set before calling idx_to_price")
        i = int(idx)
        if i < 0 or i >= len(self.column_template):
            raise ValueError(f"price index out of range: {idx}")
        return self.price_min + (Decimal(i) * self.spread)

    def idx_to_time(self, idx: int, now_epoch: int | None = None) -> int:
        if not hasattr(self, "H") or self.H is None:
            raise ValueError("H is not initialized")
        width = int(self.H.shape[1])
        i = int(idx)
        if i < 0 or i >= width:
            raise ValueError(f"time index out of range: {idx}")
        now = int(time.time()) if now_epoch is None else int(now_epoch)
        dt = (width - 1) - i
        return now - dt


    """
    Custom function to set pixel density for price and time axes.  This allows dynamic adjustment of the plot's resolution
    based on user preferences or display requirements. By providing separate methods for price and time density, users can
    fine-tune the visualization to better suit their needs, ensuring that the plot remains clear and informative regardless
    of the data being displayed.
    """
    def _set_pixel_density(self, price_density = None, time_density = None):
        """
        @params:
        price_density — # of pixels / price bin
        time_density — # of pixels / time second
        """
        if (not price_density and not time_density) or (not price_density.isdigit() and int(price_density) > 0) or (not time_density.isdigit() and int(time_density) > 0):
            raise ValueError("At least one of price_density or time_density must be provided.")
        if price_density:
            self.price_density = price_density
            #TODO: add code to adjust the plot's price axis resolution based on the new price_density value
            # if self.price_min and self.price_max and self.spread:

        if time_density:
            self.time_density = time_density
            #TODO: add code to adjust the plot's time axis resolution based on the new time_density value

    def set_price_density(self, price_density):
        self._set_pixel_density(price_density=price_density)

    def set_time_density(self, time_density):
        self._set_pixel_density(time_density=time_density)

    """
    The actual matrix of plot info should be greater than the display window to allow for smooth scrolling and to avoid
    edge cases where the plot runs out of data to display. By caching a range of price levels that extends beyond the
    visible area, the plot can seamlessly update as new data comes in or as the user scrolls through the price history.
    This approach ensures that the visualization remains responsive and informative, providing a better user experience.
    """
    def _set_quote_settings(self, spread = None, price_min = None, price_max = None):
        """
        @params:
        spread — minimum price increment (tick size)
        price_min - minimum price level to cache for display
        price_max - maximum price level to cache for display
        """
        if (not spread or not price_min or not price_max) or (not spread.isdigit() and float(spread) > 0) or (not price_min.isdigit() and float(price_min) > 0) or (not price_max.isdigit() and float(price_max) > 0):
            raise ValueError("spread, price_min, and price_max must be provided and must be positive numbers.")
        if spread:
            self.spread = spread
        if price_min:
            self.price_min = price_min
        if price_max:
            self.price_max = price_max

    def set_spread(self, spread):
        self._set_quote_settings(spread=spread)

    def set_price_min(self, price_min):
        self._set_quote_settings(price_min=price_min)

    def set_price_max(self, price_max):
        self._set_quote_settings(price_max=price_max)


if __name__ == "__main__":
    plot = PlotA(plot_width=800, plot_height=600, price_density=1, time_density=1, spread=Decimal("0.01"), price_min=Decimal("1"), price_max=Decimal("5"))
    print(plot.H, plot.H.shape)
    assert plot.price_to_idx(Decimal("1.00")) == 0
    assert plot.price_to_idx(Decimal("1.01")) == 1
    try:
        plot.price_to_idx(Decimal("1.001"))
        assert False, "Expected ValueError"
    except ValueError as e:
        assert str(e) == "price is off-grid"
    assert plot.price_to_idx(Decimal("0.99")) == -1
    assert plot.price_to_idx(Decimal("5.00")) == 400
    pass
